#!/usr/bin/env python3
"""AWS go-live wizard against mocked AWS (moto). No real account needed.

    pip install boto3 "moto[s3,acm,cloudfront,route53]"
    python3 tests/test_aws_setup.py

Skips (exit 0) when boto3 or moto isn't installed.
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    import boto3
    from moto import mock_aws
except ImportError:
    print("skip: pip install boto3 'moto[s3,acm,cloudfront,route53]' to run the AWS tests")
    sys.exit(0)

from proofpress import aws, project as pj, secrets  # noqa: E402

failures = []
DEMO = ROOT / "examples/demo-project"


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        failures.append(name)


REAL_SESSION = aws.session


def mocked_session_factory(state):
    """Session with fixes for operations moto doesn't fully emulate."""
    real = REAL_SESSION

    def fake(project, settings=None):
        sess = real(project, settings)
        ev = sess.events

        def publish_fn(params, **kw):  # moto: PublishFunction is not implemented
            return (type("R", (), {"status_code": 200, "headers": {}})(),
                    {"FunctionSummary": {"Name": "fn", "FunctionMetadata": {"Stage": "LIVE"}}})

        def cert_status(parsed, **kw):  # moto keeps certificates pending forever
            if state.get("issue") and "Certificate" in parsed:
                parsed["Certificate"]["Status"] = "ISSUED"

        def dist_status(parsed, **kw):
            if "Distribution" in parsed:
                parsed["Distribution"]["Status"] = "Deployed" if state.get("deployed") else "InProgress"

        ev.register("before-call.cloudfront.PublishFunction", publish_fn)
        ev.register("after-call.acm.DescribeCertificate", cert_status)
        ev.register("after-call.cloudfront.GetDistribution", dist_status)
        return sess
    return fake


class FakeResp:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def T(service):
    return boto3.Session(aws_access_key_id="testing", aws_secret_access_key="testing",
                         region_name="us-east-1").client(service)


def run_case(tmp, domain, with_zone):
    proj = tmp / domain
    shutil.copytree(DEMO, proj)
    s = pj.load(proj)
    s["publish"]["s3"]["credentials"] = "keys"
    pj.save(proj, s)
    secrets.set_many(proj, {"AWS_ACCESS_KEY_ID": "AKIAEXAMPLEKEY12345", "AWS_SECRET_ACCESS_KEY": "secretsecretsecret"})
    os.environ.pop("AWS_ACCESS_KEY_ID", None)
    os.environ.pop("AWS_SECRET_ACCESS_KEY", None)

    state = {}
    aws.session = mocked_session_factory(state)
    aws.urllib.request.urlopen = lambda *a, **k: FakeResp()

    r53 = T("route53")
    if with_zone:
        zid = r53.create_hosted_zone(Name="example.org", CallerReference="z1")["HostedZone"]["Id"]
        # leftover CNAME (e.g. from a previous host) must not block the alias records
        r53.change_resource_record_sets(HostedZoneId=zid, ChangeBatch={"Changes": [{"Action": "CREATE", "ResourceRecordSet": {
            "Name": "www.example.org", "Type": "CNAME", "TTL": 300, "ResourceRecords": [{"Value": "old-host.example.net"}]}}]})

    who = aws.identity(proj)
    check(f"[{domain}] identity", who["account"] == "123456789012", who)
    info = aws.check_domain(proj, "https://" + domain + "/")
    check(f"[{domain}] domain normalised", info["domain"] == domain, info)
    check(f"[{domain}] zone detection", bool(info["zone"]) == with_zone, info)

    p = aws.Provisioner(proj, domain, "us-east-1")
    for key, _ in aws.STEPS:
        if key == "cert_issued":
            try:
                p.step_cert_issued()
                check(f"[{domain}] cert waits until validated", False)
            except aws.Wait:
                check(f"[{domain}] cert waits until validated", True)
            state["issue"] = True
        if key == "deployed":
            try:
                p.step_deployed()
                check(f"[{domain}] waits for CloudFront rollout", False)
            except aws.Wait:
                check(f"[{domain}] waits for CloudFront rollout", True)
            state["deployed"] = True
        detail = getattr(p, "step_" + key)()
        p.mark(key, "done", detail)

    st = aws.read_state(proj)
    s3 = T("s3")
    check(f"[{domain}] bucket created and private", s3.get_public_access_block(Bucket=st["bucket"])["PublicAccessBlockConfiguration"]["BlockPublicPolicy"])
    pol = json.loads(s3.get_bucket_policy(Bucket=st["bucket"])["Policy"])
    check(f"[{domain}] bucket policy limited to the distribution", st["distribution_id"] in json.dumps(pol))
    cf = T("cloudfront")
    d = cf.get_distribution(Id=st["distribution_id"])["Distribution"]["DistributionConfig"]
    check(f"[{domain}] distribution aliases", d["Aliases"]["Items"] == st["aliases"], d["Aliases"])
    check(f"[{domain}] distribution uses certificate", d["ViewerCertificate"]["ACMCertificateArn"] == st["cert_arn"])
    keys = [o["Key"] for o in s3.list_objects_v2(Bucket=st["bucket"]).get("Contents", [])]
    check(f"[{domain}] site uploaded", "index.html" in keys and any(k.startswith("blog/") for k in keys), keys[:5])
    html_ct = s3.head_object(Bucket=st["bucket"], Key="index.html")["ContentType"]
    check(f"[{domain}] html content type", html_ct.startswith("text/html"), html_ct)
    s2 = pj.load(proj)
    check(f"[{domain}] settings written", s2["site"]["base_url"] == "https://" + domain and s2["publish"]["s3"]["bucket"] == st["bucket"]
          and s2["publish"]["site_provider"] == "s3")

    if with_zone:
        recs = r53.list_resource_record_sets(HostedZoneId=st["zone"]["id"])["ResourceRecordSets"]
        aliases = {(r["Name"].rstrip("."), r["Type"]) for r in recs if r.get("AliasTarget")}
        check(f"[{domain}] Route 53 alias records", {(domain, "A"), ("www." + domain, "AAAA")} <= aliases, aliases)
        check(f"[{domain}] no manual DNS needed", st["dns_for_user"] == [])
        cnames = [r for r in recs if r["Name"].rstrip(".") == "www." + domain and r["Type"] == "CNAME"]
        check(f"[{domain}] conflicting CNAME replaced", not cnames, cnames)
    else:
        kinds = sorted({r["purpose"] for r in st["dns_for_user"]})
        check(f"[{domain}] manual DNS records listed", kinds == ["certificate", "site"], st["dns_for_user"])

    # idempotent: a second full run reuses everything
    before = (st["bucket"], st["cert_arn"], st["distribution_id"])
    p2 = aws.Provisioner(proj, domain, "us-east-1")
    p2.run()
    st2 = aws.read_state(proj)
    check(f"[{domain}] rerun reuses resources", before == (st2["bucket"], st2["cert_arn"], st2["distribution_id"]) and not st2.get("error"),
          st2.get("error"))

    # reset + different region: the existing bucket's real region must be used for the origin
    aws.reset(proj)
    p3 = aws.Provisioner(proj, domain, "eu-west-1")
    p3.step_identity(); p3.step_domain(); detail = p3.step_bucket()
    check(f"[{domain}] reused bucket keeps its real region", p3.st["region"] == "us-east-1" and "us-east-1" in detail, detail)

    # publishing later goes through boto3 too
    from proofpress.publish import publish
    res = publish(proj)
    check(f"[{domain}] publish uploads with saved keys", any("invalidated CloudFront" in x for x in res["log"]), res["log"])


def main():
    os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
    tmp = Path(tempfile.mkdtemp(prefix="pp-aws-"))
    try:
        with mock_aws():
            run_case(tmp, "example.org", with_zone=True)
        with mock_aws():
            run_case(tmp, "www.external-dns.net", with_zone=False)
        check("bare-domain warning", aws.looks_apex("example.com") and aws.looks_apex("example.co.jp") and not aws.looks_apex("www.example.com"))
        try:
            aws.normalize_domain("not a domain")
            check("bad domain rejected", False)
        except aws.AwsError:
            check("bad domain rejected", True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{len(failures)} failure(s)" if failures else "\nall AWS checks passed")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
