"""AWS go-live: provision S3 + CloudFront + ACM (+ Route 53) for a domain, as the user.

Everything runs with the user's own AWS credentials (access keys saved on the settings
page, or an AWS CLI profile on this computer). Each step is idempotent and its result is
saved in .proofpress/aws_setup.json, so an interrupted setup resumes where it stopped.

Steps:
  identity      check the credentials work
  domain        find a Route 53 hosted zone for the domain (fully automatic DNS) or not
  bucket        private S3 bucket for the site files
  certificate   ACM certificate in us-east-1 (DNS validation)
  cert_dns      validation records: written to Route 53, or shown to the user
  cert_issued   wait until the certificate is issued
  oac           CloudFront Origin Access Control (CloudFront may read the bucket, nobody else)
  function      CloudFront Function: /path/ -> /path/index.html, www <-> apex redirect
  distribution  CloudFront distribution with the domain, certificate and function
  bucket_policy allow only this distribution to read the bucket
  site_dns      A/AAAA alias records in Route 53, or a CNAME shown to the user
  settings      write bucket, distribution, region and site URL into proofpress.json
  deployed      wait until CloudFront has rolled the distribution out
  first_publish build the site and upload it
  live_check    https://<domain>/ answers
"""
import datetime as dt
import hashlib
import json
import mimetypes
import re
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import secrets
from .project import load, root, save

CACHING_OPTIMIZED = "658327ea-f89d-4fab-a63d-7e88639e58f6"  # AWS managed cache policy
CLOUDFRONT_ZONE_ID = "Z2FDTNDATAQYW2"  # hosted zone id for every CloudFront alias target
STATE = ".proofpress/aws_setup.json"

STEPS = [
    ("identity", "Check AWS credentials"),
    ("domain", "Look up the domain's DNS"),
    ("bucket", "Create private S3 bucket"),
    ("certificate", "Request HTTPS certificate"),
    ("cert_dns", "Add certificate validation records"),
    ("cert_issued", "Wait for the certificate"),
    ("oac", "Create CloudFront origin access"),
    ("function", "Create URL rewrite function"),
    ("distribution", "Create CloudFront distribution"),
    ("bucket_policy", "Lock the bucket to CloudFront"),
    ("site_dns", "Point the domain at CloudFront"),
    ("settings", "Save settings"),
    ("deployed", "Wait for CloudFront to deploy"),
    ("first_publish", "Build and upload the site"),
    ("live_check", "Check the site is live"),
]

POLICY = {
    "Version": "2012-10-17",
    "Statement": [
        {"Sid": "Identity", "Effect": "Allow", "Action": ["sts:GetCallerIdentity"], "Resource": "*"},
        {"Sid": "SiteBucket", "Effect": "Allow",
         "Action": ["s3:CreateBucket", "s3:ListBucket", "s3:GetBucketLocation", "s3:PutBucketPolicy",
                    "s3:GetBucketPolicy", "s3:PutBucketPublicAccessBlock", "s3:PutBucketTagging",
                    "s3:PutObject", "s3:GetObject", "s3:DeleteObject"],
         "Resource": ["arn:aws:s3:::pp-*", "arn:aws:s3:::pp-*/*"]},
        {"Sid": "Certificates", "Effect": "Allow",
         "Action": ["acm:RequestCertificate", "acm:DescribeCertificate", "acm:ListCertificates", "acm:AddTagsToCertificate"],
         "Resource": "*"},
        {"Sid": "CloudFront", "Effect": "Allow",
         "Action": ["cloudfront:CreateDistribution", "cloudfront:GetDistribution", "cloudfront:ListDistributions",
                    "cloudfront:TagResource", "cloudfront:CreateInvalidation",
                    "cloudfront:CreateOriginAccessControl", "cloudfront:ListOriginAccessControls",
                    "cloudfront:CreateFunction", "cloudfront:UpdateFunction", "cloudfront:DescribeFunction",
                    "cloudfront:PublishFunction", "cloudfront:ListFunctions"],
         "Resource": "*"},
        {"Sid": "Dns", "Effect": "Allow",
         "Action": ["route53:ListHostedZones", "route53:ListHostedZonesByName", "route53:ChangeResourceRecordSets",
                    "route53:ListResourceRecordSets", "route53:GetChange"],
         "Resource": "*"},
    ],
}

FUNCTION_CODE = """function handler(event) {
  var req = event.request;
  var host = req.headers.host ? req.headers.host.value : '';
  var redirectFrom = __REDIRECT__;
  if (redirectFrom.indexOf(host) !== -1) {
    return { statusCode: 301, statusDescription: 'Moved Permanently',
             headers: { location: { value: 'https://__CANONICAL__' + req.uri } } };
  }
  var uri = req.uri;
  if (uri.endsWith('/')) { req.uri = uri + 'index.html'; }
  else if (uri.split('/').pop().indexOf('.') === -1) { req.uri = uri + '/index.html'; }
  return req;
}
"""


class AwsError(Exception):
    pass


class Wait(Exception):
    """Raised by a step that is waiting on AWS or on the user; the runner polls again later."""

    def __init__(self, message, retry_after=15):
        super().__init__(message)
        self.retry_after = retry_after


# ------------------------------------------------------------------ helpers

def boto3_mod():
    try:
        import boto3  # noqa: F401
        import botocore  # noqa: F401
    except ImportError:
        raise AwsError("the AWS SDK isn't installed. Run ./install.sh again (it installs boto3), or: pip install boto3")
    import boto3
    return boto3


def normalize_domain(d):
    d = (d or "").strip().lower()
    d = re.sub(r"^[a-z]+://", "", d).split("/")[0].split(":")[0].rstrip(".")
    if not re.match(r"^(?=.{4,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$", d):
        raise AwsError(f"'{d}' doesn't look like a domain name (example: www.example.com)")
    return d


def slug_for(domain):
    return re.sub(r"[^a-z0-9]+", "-", domain).strip("-")


def session(project, settings=None):
    boto3 = boto3_mod()
    s = settings or load(project)
    c = s["publish"]["s3"]
    region = c.get("region") or "us-east-1"
    if c.get("credentials", "keys") == "keys":
        ak, sk = secrets.get(project, "AWS_ACCESS_KEY_ID"), secrets.get(project, "AWS_SECRET_ACCESS_KEY")
        if not (ak and sk):
            raise AwsError("AWS access keys aren't saved yet (Go live > step 1)")
        return boto3.Session(aws_access_key_id=ak, aws_secret_access_key=sk, region_name=region)
    prof = c.get("aws_profile") or None
    if prof and prof not in boto3.Session().available_profiles:
        prof = None
    return boto3.Session(profile_name=prof, region_name=region)


def list_profiles():
    try:
        return boto3_mod().Session().available_profiles
    except AwsError:
        return []


def identity(project, settings=None):
    try:
        sess = session(project, settings)
        who = sess.client("sts").get_caller_identity()
    except AwsError:
        raise
    except Exception as e:
        raise AwsError(_explain(e))
    return {"account": who["Account"], "arn": who["Arn"], "is_root": who["Arn"].endswith(":root")}


def _explain(e):
    name = type(e).__name__
    msg = str(e)
    if name in ("NoCredentialsError", "PartialCredentialsError"):
        return "no AWS credentials found: paste access keys in step 1, or pick a profile that exists"
    if name == "ProfileNotFound":
        return msg
    if "InvalidClientTokenId" in msg or "SignatureDoesNotMatch" in msg:
        return "AWS rejected these access keys: check both values were copied completely"
    if "AccessDenied" in msg or "not authorized" in msg:
        return "AWS says this user isn't allowed to do that. Attach the ProofPress policy shown in step 1. Details: " + msg[:300]
    return f"{name}: {msg[:400]}"


def find_zone(sess, domain):
    r53 = sess.client("route53")
    best = None
    for page in r53.get_paginator("list_hosted_zones").paginate():
        for z in page["HostedZones"]:
            if z.get("Config", {}).get("PrivateZone"):
                continue
            name = z["Name"].rstrip(".")
            if domain == name or domain.endswith("." + name):
                if not best or len(name) > len(best["name"]):
                    best = {"id": z["Id"].split("/")[-1], "name": name}
    return best


SECOND_LEVEL = {"co", "com", "net", "org", "ac", "gov", "ne", "or", "edu"}


def looks_apex(domain):
    labels = domain.split(".")
    return len(labels) == 2 or (len(labels) == 3 and labels[1] in SECOND_LEVEL and len(labels[2]) == 2)


def check_domain(project, domain, settings=None):
    domain = normalize_domain(domain)
    sess = session(project, settings)
    try:
        zone = find_zone(sess, domain)
    except Exception as e:
        raise AwsError(_explain(e))
    return {"domain": domain, "zone": zone, "aliases": plan_aliases(domain, zone),
            "apex_warning": (not zone) and looks_apex(domain)}


def plan_aliases(domain, zone):
    aliases = [domain]
    if zone:
        if domain == zone["name"]:
            aliases.append("www." + domain)
        elif domain == "www." + zone["name"]:
            aliases.append(zone["name"])
    return aliases


def _now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


# ------------------------------------------------------------------ state

def state_path(project):
    p = root(project) / STATE
    p.parent.mkdir(parents=True, exist_ok=True)
    gi = p.parent / ".gitignore"
    if not gi.exists():
        gi.write_text("*\n", encoding="utf-8")
    return p


def read_state(project):
    p = state_path(project)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            pass
    return {}


def write_state(project, st):
    p = state_path(project)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(p)


def public_state(project):
    st = read_state(project)
    steps = st.get("steps", {})
    st["steps_list"] = [{"id": k, "label": label, **steps.get(k, {"status": "pending"})} for k, label in STEPS]
    run = RUNNERS.get(str(root(project)))
    st["running"] = bool(run and run.is_alive())
    return st


# ------------------------------------------------------------------ the provisioning steps

class Provisioner:
    def __init__(self, project, domain=None, region=None):
        self.project = project
        self.settings = load(project)
        st = read_state(project)
        if domain:
            domain = normalize_domain(domain)
            if st.get("domain") and st["domain"] != domain:
                st = {}
            st["domain"] = domain
        if region:
            if st.get("region") and st["region"] != region and st.get("bucket"):
                raise AwsError("the bucket already exists in another region; reset the setup to change region")
            st["region"] = region
        if not st.get("domain"):
            raise AwsError("enter a domain first")
        st.setdefault("region", "us-east-1")
        st.setdefault("steps", {})
        st.setdefault("dns_for_user", [])
        self.st = st
        s3 = self.settings["publish"]["s3"]
        s3["region"] = st["region"]
        self.sess = session(project, self.settings)
        self.stop = threading.Event()

    # -- bookkeeping
    def mark(self, step, status, detail=""):
        self.st["steps"][step] = {"status": status, "detail": detail, "at": _now()}
        write_state(self.project, self.st)

    def client(self, name, region=None):
        return self.sess.client(name, region_name=region or self.st["region"])

    @property
    def domain(self):
        return self.st["domain"]

    def _user_dns(self, purpose, name, rtype, value):
        recs = [r for r in self.st["dns_for_user"] if not (r["purpose"] == purpose and r["name"] == name)]
        recs.append({"purpose": purpose, "name": name, "type": rtype, "value": value})
        self.st["dns_for_user"] = recs

    # -- steps
    def step_identity(self):
        who = identity(self.project, self.settings)
        self.st["account"] = who["account"]
        note = "signed in as " + who["arn"]
        if who["is_root"]:
            note += " (root user: works, but an IAM user with the ProofPress policy is safer)"
        return note

    def step_domain(self):
        zone = find_zone(self.sess, self.domain)
        self.st["zone"] = zone
        self.st["aliases"] = plan_aliases(self.domain, zone)
        if zone:
            return f"Route 53 hosts {zone['name']}: DNS will be configured automatically"
        note = "DNS isn't in Route 53: you'll be shown 2-3 records to add at your DNS provider"
        if looks_apex(self.domain):
            note += (". This is a bare domain: your DNS provider must support ALIAS/ANAME or CNAME flattening at the root, "
                     "otherwise use www." + self.domain + " as the site domain")
        return note

    def step_bucket(self):
        s3 = self.client("s3")
        if not self.st.get("bucket"):
            base = f"pp-{slug_for(self.domain)}"[:55].rstrip("-")
            self.st["bucket"] = f"{base}-{self.st['account'][-6:]}"
        b = self.st["bucket"]
        exists = False
        try:
            s3.head_bucket(Bucket=b)
            exists = True
        except Exception as e:
            if "403" in str(e) or "Forbidden" in str(e):
                raise AwsError(f"bucket {b} exists but belongs to someone else")
        if exists:
            # The bucket may be in another region than the one picked now (e.g. after a reset):
            # the CloudFront origin must use the bucket's real region.
            loc = s3.get_bucket_location(Bucket=b).get("LocationConstraint") or "us-east-1"
            if loc == "EU":
                loc = "eu-west-1"
            note = f"{b} (already exists"
            if loc != self.st["region"]:
                note += f"; it lives in {loc}, so {loc} is used"
                self.st["region"] = loc
            note += ")"
        else:
            kw = {"Bucket": b}
            if self.st["region"] != "us-east-1":
                kw["CreateBucketConfiguration"] = {"LocationConstraint": self.st["region"]}
            self.client("s3").create_bucket(**kw)
            note = f"created {b} in {self.st['region']}"
        s3 = self.client("s3")
        s3.put_public_access_block(Bucket=b, PublicAccessBlockConfiguration={
            "BlockPublicAcls": True, "IgnorePublicAcls": True, "BlockPublicPolicy": True, "RestrictPublicBuckets": True})
        s3.put_bucket_tagging(Bucket=b, Tagging={"TagSet": [{"Key": "proofpress", "Value": self.domain}]})
        return note

    def _acm(self):
        return self.client("acm", "us-east-1")

    def step_certificate(self):
        acm = self._acm()
        arn = self.st.get("cert_arn")
        if arn:
            try:
                status = acm.describe_certificate(CertificateArn=arn)["Certificate"]["Status"]
                if status in ("ISSUED", "PENDING_VALIDATION"):
                    return self._cert_records(arn)
            except Exception:
                pass
        want = set(self.st["aliases"])
        for page in acm.get_paginator("list_certificates").paginate(CertificateStatuses=["ISSUED", "PENDING_VALIDATION"]):
            for c in page["CertificateSummaryList"]:
                if c["DomainName"] in self.st["aliases"]:
                    cert = acm.describe_certificate(CertificateArn=c["CertificateArn"])["Certificate"]
                    if set(cert.get("SubjectAlternativeNames", [])) >= want:
                        self.st["cert_arn"] = c["CertificateArn"]
                        return self._cert_records(c["CertificateArn"], reused=True)
        token = hashlib.sha1(",".join(self.st["aliases"]).encode()).hexdigest()[:32]
        short = [a for a in self.st["aliases"] if len(a) <= 64]
        if not short:
            raise AwsError("certificates need at least one name of 64 characters or less; use a shorter domain")
        arn = acm.request_certificate(
            DomainName=short[0], SubjectAlternativeNames=self.st["aliases"],
            ValidationMethod="DNS", IdempotencyToken=token,
            Tags=[{"Key": "proofpress", "Value": self.domain}])["CertificateArn"]
        self.st["cert_arn"] = arn
        write_state(self.project, self.st)
        return self._cert_records(arn)

    def _cert_records(self, arn, reused=False):
        acm = self._acm()
        for _ in range(20):
            try:
                cert = acm.describe_certificate(CertificateArn=arn)["Certificate"]
            except Exception as e:
                if "ResourceNotFound" not in str(e) and "ResourceNotFound" not in type(e).__name__:
                    raise
                if self.stop.wait(3):
                    raise Wait("stopped")
                continue
            opts = cert.get("DomainValidationOptions", [])
            recs = [o["ResourceRecord"] for o in opts if o.get("ResourceRecord")]
            if cert["Status"] == "ISSUED" or (opts and len(recs) == len(opts)):
                uniq = {(r["Name"], r["Value"]): r for r in recs}
                self.st["cert_records"] = [{"name": r["Name"], "type": r["Type"], "value": r["Value"]} for r in uniq.values()]
                return ("reusing " if reused else "requested ") + arn.split("/")[-1]
            if self.stop.wait(3):
                raise Wait("stopped")
        raise Wait("AWS is still preparing the validation records", 10)

    def _upsert(self, changes):
        r53 = self.client("route53")
        r53.change_resource_record_sets(HostedZoneId=self.st["zone"]["id"], ChangeBatch={"Changes": changes})

    def step_cert_dns(self):
        recs = self.st.get("cert_records", [])
        if self._acm().describe_certificate(CertificateArn=self.st["cert_arn"])["Certificate"]["Status"] == "ISSUED":
            return "certificate already issued"
        if self.st.get("zone"):
            self._upsert([{"Action": "UPSERT", "ResourceRecordSet": {
                "Name": r["name"], "Type": r["type"], "TTL": 300, "ResourceRecords": [{"Value": r["value"]}]}} for r in recs])
            return f"added {len(recs)} validation record(s) to Route 53"
        for r in recs:
            self._user_dns("certificate", r["name"].rstrip("."), r["type"], r["value"].rstrip("."))
        return "action needed: add the certificate records shown below at your DNS provider"

    def step_cert_issued(self):
        cert = self._acm().describe_certificate(CertificateArn=self.st["cert_arn"])["Certificate"]
        status = cert["Status"]
        if status == "ISSUED":
            return "issued"
        if status in ("FAILED", "VALIDATION_TIMED_OUT", "REVOKED", "EXPIRED"):
            raise AwsError(f"certificate {status}: {cert.get('FailureReason', '')}. Reset and try again.")
        who = "AWS (usually 2-10 minutes)" if self.st.get("zone") else "your DNS records (minutes to a few hours after you add them)"
        raise Wait(f"waiting for validation by {who}", 20)

    def _cf(self):
        return self.client("cloudfront", "us-east-1")

    def _name(self):
        return f"pp-{slug_for(self.domain)}"[:64]

    def step_oac(self):
        cf = self._cf()
        if self.st.get("oac_id"):
            return self.st["oac_id"]
        marker = None
        while True:
            kw = {"Marker": marker} if marker else {}
            lst = cf.list_origin_access_controls(**kw).get("OriginAccessControlList", {})
            for item in lst.get("Items", []) or []:
                if item["Name"] == self._name():
                    self.st["oac_id"] = item["Id"]
                    return f"reusing {item['Id']}"
            marker = lst.get("NextMarker")
            if not lst.get("IsTruncated") or not marker:
                break
        oac = cf.create_origin_access_control(OriginAccessControlConfig={
            "Name": self._name(), "Description": f"ProofPress {self.domain}", "SigningProtocol": "sigv4",
            "SigningBehavior": "always", "OriginAccessControlOriginType": "s3"})
        self.st["oac_id"] = oac["OriginAccessControl"]["Id"]
        return f"created {self.st['oac_id']}"

    def step_function(self):
        cf = self._cf()
        name = self._name()
        others = [a for a in self.st["aliases"] if a != self.domain]
        code = FUNCTION_CODE.replace("__REDIRECT__", json.dumps(others)).replace("__CANONICAL__", self.domain).encode()
        cfg = {"Comment": f"ProofPress {self.domain}"[:128], "Runtime": "cloudfront-js-2.0"}
        try:
            etag = cf.describe_function(Name=name)["ETag"]
            etag = cf.update_function(Name=name, IfMatch=etag, FunctionConfig=cfg, FunctionCode=code)["ETag"]
        except Exception as e:
            if "NoSuchFunction" not in str(e) and "404" not in str(e) and "NotFound" not in type(e).__name__:
                raise
            etag = cf.create_function(Name=name, FunctionConfig=cfg, FunctionCode=code)["ETag"]
        cf.publish_function(Name=name, IfMatch=etag)
        self.st["function_arn"] = cf.describe_function(Name=name, Stage="LIVE")["FunctionSummary"]["FunctionMetadata"]["FunctionARN"]
        return f"published {name}"

    def step_distribution(self):
        cf = self._cf()
        comment = f"ProofPress {self.domain}"[:128]
        if not self.st.get("distribution_id"):
            for page in cf.get_paginator("list_distributions").paginate():
                for d in (page.get("DistributionList", {}).get("Items") or []):
                    if d.get("Comment") == comment:
                        self.st["distribution_id"] = d["Id"]
                        self.st["distribution_domain"] = d["DomainName"]
        if self.st.get("distribution_id"):
            return f"reusing {self.st['distribution_id']}"
        b = self.st["bucket"]
        origin_id = "s3-" + b
        cfg = {
            "CallerReference": f"proofpress-{slug_for(self.domain)[:60]}-{int(time.time())}",
            "Comment": comment,
            "Enabled": True,
            "Aliases": {"Quantity": len(self.st["aliases"]), "Items": self.st["aliases"]},
            "DefaultRootObject": "index.html",
            "Origins": {"Quantity": 1, "Items": [{
                "Id": origin_id,
                "DomainName": f"{b}.s3.{self.st['region']}.amazonaws.com",
                "S3OriginConfig": {"OriginAccessIdentity": ""},
                "OriginAccessControlId": self.st["oac_id"],
            }]},
            "DefaultCacheBehavior": {
                "TargetOriginId": origin_id,
                "ViewerProtocolPolicy": "redirect-to-https",
                "CachePolicyId": CACHING_OPTIMIZED,
                "Compress": True,
                "AllowedMethods": {"Quantity": 2, "Items": ["GET", "HEAD"],
                                   "CachedMethods": {"Quantity": 2, "Items": ["GET", "HEAD"]}},
                "FunctionAssociations": {"Quantity": 1, "Items": [
                    {"FunctionARN": self.st["function_arn"], "EventType": "viewer-request"}]},
            },
            "CustomErrorResponses": {"Quantity": 2, "Items": [
                {"ErrorCode": 403, "ResponsePagePath": "/404.html", "ResponseCode": "404", "ErrorCachingMinTTL": 60},
                {"ErrorCode": 404, "ResponsePagePath": "/404.html", "ResponseCode": "404", "ErrorCachingMinTTL": 60},
            ]},
            "ViewerCertificate": {"ACMCertificateArn": self.st["cert_arn"], "SSLSupportMethod": "sni-only",
                                  "MinimumProtocolVersion": "TLSv1.2_2021"},
            "HttpVersion": "http2and3",
            "IsIPV6Enabled": True,
            "PriceClass": "PriceClass_All",
        }
        d = cf.create_distribution_with_tags(DistributionConfigWithTags={
            "DistributionConfig": cfg, "Tags": {"Items": [{"Key": "proofpress", "Value": self.domain}]}})["Distribution"]
        self.st["distribution_id"] = d["Id"]
        self.st["distribution_domain"] = d["DomainName"]
        return f"created {d['Id']} ({d['DomainName']})"

    def step_bucket_policy(self):
        arn = f"arn:aws:cloudfront::{self.st['account']}:distribution/{self.st['distribution_id']}"
        policy = {"Version": "2012-10-17", "Statement": [{
            "Sid": "AllowCloudFrontOnly", "Effect": "Allow",
            "Principal": {"Service": "cloudfront.amazonaws.com"},
            "Action": "s3:GetObject", "Resource": f"arn:aws:s3:::{self.st['bucket']}/*",
            "Condition": {"StringEquals": {"AWS:SourceArn": arn}}}]}
        self.client("s3").put_bucket_policy(Bucket=self.st["bucket"], Policy=json.dumps(policy))
        return "only this CloudFront distribution can read the files"

    def step_site_dns(self):
        target = self.st["distribution_domain"]
        if self.st.get("zone"):
            changes = []
            r53 = self.client("route53")
            for a in self.st["aliases"]:
                # A CNAME can't coexist with the alias records (e.g. left over from Netlify or a parking page).
                found = r53.list_resource_record_sets(HostedZoneId=self.st["zone"]["id"], StartRecordName=a,
                                                      StartRecordType="CNAME", MaxItems="1")["ResourceRecordSets"]
                for rr in found:
                    if rr["Name"].rstrip(".") == a and rr["Type"] == "CNAME":
                        changes.append({"Action": "DELETE", "ResourceRecordSet": rr})
                for t in ("A", "AAAA"):
                    changes.append({"Action": "UPSERT", "ResourceRecordSet": {
                        "Name": a, "Type": t, "AliasTarget": {
                            "HostedZoneId": CLOUDFRONT_ZONE_ID, "DNSName": target, "EvaluateTargetHealth": False}}})
            self._upsert(changes)
            return f"{', '.join(self.st['aliases'])} → {target}"
        for a in self.st["aliases"]:
            self._user_dns("site", a, "CNAME", target)
        return "action needed: add the CNAME shown below at your DNS provider"

    def step_settings(self):
        s = load(self.project)
        s["site"]["base_url"] = "https://" + self.domain
        s["publish"]["mode"] = "site"
        s["publish"]["site_provider"] = "s3"
        s3 = s["publish"]["s3"]
        s3["bucket"] = self.st["bucket"]
        s3["cloudfront_distribution_id"] = self.st["distribution_id"]
        s3["region"] = self.st["region"]
        cur = self.settings["publish"]["s3"]
        s3["credentials"] = cur.get("credentials", "keys")
        s3["aws_profile"] = cur.get("aws_profile", "default")
        save(self.project, s)
        self.settings = s
        return f"site URL https://{self.domain}, publishing to S3 + CloudFront"

    def step_deployed(self):
        d = self._cf().get_distribution(Id=self.st["distribution_id"])["Distribution"]
        if d["Status"] == "Deployed":
            return "deployed worldwide"
        raise Wait("CloudFront is rolling out the distribution (usually 3-15 minutes)", 30)

    def step_first_publish(self):
        from .build import BuildError, build
        try:
            res = build(self.project)
        except BuildError as e:
            return f"skipped: {e}"
        log = []
        s3_upload(self.project, load(self.project), root(self.project) / "public", log, dry=False)
        return f"uploaded {len(res['articles'])} article(s) + homepage; " + (log[-1] if log else "")

    def step_live_check(self):
        url = f"https://{self.domain}/"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "ProofPress live check"})
            with urllib.request.urlopen(req, timeout=15) as r:
                if r.status == 200:
                    return f"{url} is live"
                raise Wait(f"{url} answered HTTP {r.status}", 30)
        except urllib.error.HTTPError as e:
            raise Wait(f"{url} answered HTTP {e.code}", 30)
        except Exception as e:
            hint = "DNS may still be propagating" if self.st.get("zone") else "add the DNS records below if you haven't; then DNS needs time to propagate"
            raise Wait(f"not reachable yet ({type(e).__name__}); {hint}", 30)

    # -- runner
    def run(self):
        self.st.pop("error", None)
        self.st["started_at"] = self.st.get("started_at") or _now()
        write_state(self.project, self.st)
        for key, _label in STEPS:
            if self.st["steps"].get(key, {}).get("status") == "done" and key not in ("deployed", "live_check"):
                continue
            fn = getattr(self, "step_" + key)
            waited = 0
            while True:
                if self.stop.is_set():
                    self.mark(key, "paused", "stopped; press Continue to resume")
                    return
                self.mark(key, "running", "")
                try:
                    detail = fn()
                    self.mark(key, "done", detail or "")
                    break
                except Wait as w:
                    waited += w.retry_after
                    mins = waited // 60
                    self.mark(key, "waiting", f"{w} · waited {mins} min" if mins else str(w))
                    if self.stop.wait(w.retry_after):
                        self.mark(key, "paused", "stopped; press Continue to resume")
                        return
                except AwsError as e:
                    self.mark(key, "error", str(e))
                    self.st["error"] = str(e)
                    write_state(self.project, self.st)
                    return
                except Exception as e:
                    msg = _explain(e)
                    self.mark(key, "error", msg)
                    self.st["error"] = msg
                    write_state(self.project, self.st)
                    return
        self.st["finished_at"] = _now()
        write_state(self.project, self.st)


RUNNERS = {}


class Runner(threading.Thread):
    def __init__(self, prov):
        super().__init__(daemon=True)
        self.prov = prov

    def run(self):
        self.prov.run()


def start(project, domain=None, region=None):
    key = str(root(project))
    cur = RUNNERS.get(key)
    if cur and cur.is_alive():
        return public_state(project)
    prov = Provisioner(project, domain, region)
    write_state(project, prov.st)
    t = Runner(prov)
    RUNNERS[key] = t
    t.start()
    return public_state(project)


def stop(project):
    cur = RUNNERS.get(str(root(project)))
    if cur and cur.is_alive():
        cur.prov.stop.set()
        cur.join(timeout=10)
    return public_state(project)


def reset(project):
    stop(project)
    p = state_path(project)
    if p.exists():
        p.unlink()
    return public_state(project)


# ------------------------------------------------------------------ deploy with boto3

TEXT_TYPES = ("text/", "application/json", "application/xml", "application/javascript", "image/svg+xml")


def _content_type(path):
    ct = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    if path.suffix == ".xml":
        ct = "application/xml"
    if ct.startswith(TEXT_TYPES):
        ct += "; charset=utf-8"
    return ct


def s3_upload(project, settings, pub, log, dry=False):
    """Sync public/ to the bucket (upload changed files, delete removed ones), then invalidate CloudFront."""
    c = settings["publish"]["s3"]
    bucket, dist = c["bucket"], c["cloudfront_distribution_id"]
    files = {p.relative_to(pub).as_posix(): p for p in Path(pub).rglob("*") if p.is_file()}
    if dry:
        log.append(f"would upload changed files among {len(files)} to s3://{bucket}/, delete files removed from public/, "
                   f"and invalidate CloudFront {dist}")
        return
    sess = session(project, settings)
    s3 = sess.client("s3")
    existing = {}
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket):
        for o in page.get("Contents", []) or []:
            existing[o["Key"]] = o["ETag"].strip('"')
    up = 0
    for key, p in sorted(files.items()):
        data = p.read_bytes()
        if existing.get(key) == hashlib.md5(data).hexdigest():
            continue
        img = p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".svg", ".gif", ".ico")
        s3.put_object(Bucket=bucket, Key=key, Body=data, ContentType=_content_type(p),
                      CacheControl="public, max-age=604800" if img else "public, max-age=300")
        up += 1
    gone = [k for k in existing if k not in files]
    for i in range(0, len(gone), 1000):
        s3.delete_objects(Bucket=bucket, Delete={"Objects": [{"Key": k} for k in gone[i:i + 1000]], "Quiet": True})
    sess.client("cloudfront", region_name="us-east-1").create_invalidation(DistributionId=dist, InvalidationBatch={
        "Paths": {"Quantity": 1, "Items": ["/*"]}, "CallerReference": f"proofpress-{time.time_ns()}"})
    log.append(f"uploaded {up} changed file(s), removed {len(gone)}, invalidated CloudFront {dist}")
