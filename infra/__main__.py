"""
Career Presentation — scalable static-site infrastructure (Pulumi + Python).

Architecture
------------
    GitHub Actions ──(OIDC, no secrets)──▶ IAM Role
          │  s3 sync + CloudFront invalidation
          ▼
    ┌──────────────┐        OAC (signed)        ┌────────────────────┐
    │  S3 (private) │ ◀───────────────────────── │  CloudFront (CDN)   │ ◀── visitors (HTTPS)
    └──────────────┘                             └────────────────────┘

The S3 bucket is fully private; only CloudFront may read it, using an
Origin Access Control (OAC). CloudFront terminates TLS, caches globally
and serves the site on its default *.cloudfront.net domain.
"""

import json

import pulumi
import pulumi_aws as aws

# --------------------------------------------------------------------------- #
# Configuration                                                               #
# --------------------------------------------------------------------------- #
config = pulumi.Config()
project = pulumi.get_project()
stack = pulumi.get_stack()

github_org = config.get("githubOrg") or "rafaelhueb92"
github_repo = config.get("githubRepo") or "career-presentation"
github_branch = config.get("githubBranch") or "main"
price_class = config.get("priceClass") or "PriceClass_100"

name_prefix = f"{project}-{stack}"
common_tags = {
    "project": project,
    "stack": stack,
    "managed-by": "pulumi",
    "owner": "rafael-hueb",
}

# --------------------------------------------------------------------------- #
# 1. Private S3 bucket (origin)                                               #
# --------------------------------------------------------------------------- #
site_bucket = aws.s3.BucketV2(
    "site-bucket",
    bucket_prefix=f"{name_prefix}-",
    tags=common_tags,
)

# Serve everything through CloudFront — keep the bucket completely private.
aws.s3.BucketPublicAccessBlock(
    "site-bucket-pab",
    bucket=site_bucket.id,
    block_public_acls=True,
    block_public_policy=True,
    ignore_public_acls=True,
    restrict_public_buckets=True,
)

aws.s3.BucketVersioningV2(
    "site-bucket-versioning",
    bucket=site_bucket.id,
    versioning_configuration={"status": "Enabled"},
)

aws.s3.BucketServerSideEncryptionConfigurationV2(
    "site-bucket-encryption",
    bucket=site_bucket.id,
    rules=[
        {
            "apply_server_side_encryption_by_default": {"sse_algorithm": "AES256"},
            "bucket_key_enabled": True,
        }
    ],
)

# --------------------------------------------------------------------------- #
# 2. CloudFront distribution                                                  #
# --------------------------------------------------------------------------- #
oac = aws.cloudfront.OriginAccessControl(
    "site-oac",
    description=f"OAC for {name_prefix}",
    origin_access_control_origin_type="s3",
    signing_behavior="always",
    signing_protocol="sigv4",
)

# AWS-managed "CachingOptimized" policy — sensible defaults + compression.
caching_optimized_id = "658327ea-f89d-4fab-a63d-7e88639e58f6"

distribution = aws.cloudfront.Distribution(
    "site-cdn",
    enabled=True,
    is_ipv6_enabled=True,
    comment=f"{name_prefix} static site",
    default_root_object="index.html",
    price_class=price_class,
    http_version="http2and3",
    origins=[
        {
            "origin_id": "s3-origin",
            "domain_name": site_bucket.bucket_regional_domain_name,
            "origin_access_control_id": oac.id,
        }
    ],
    default_cache_behavior={
        "target_origin_id": "s3-origin",
        "viewer_protocol_policy": "redirect-to-https",
        "allowed_methods": ["GET", "HEAD", "OPTIONS"],
        "cached_methods": ["GET", "HEAD"],
        "compress": True,
        "cache_policy_id": caching_optimized_id,
    },
    # Single-page site: route "not found" paths back to the landing page.
    custom_error_responses=[
        {
            "error_code": 403,
            "response_code": 200,
            "response_page_path": "/index.html",
            "error_caching_min_ttl": 10,
        },
        {
            "error_code": 404,
            "response_code": 200,
            "response_page_path": "/index.html",
            "error_caching_min_ttl": 10,
        },
    ],
    restrictions={"geo_restriction": {"restriction_type": "none"}},
    viewer_certificate={"cloudfront_default_certificate": True},
    tags=common_tags,
)

# Allow only this CloudFront distribution to read from the bucket (OAC).
bucket_policy_doc = pulumi.Output.all(site_bucket.arn, distribution.arn).apply(
    lambda args: json.dumps(
        {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Sid": "AllowCloudFrontServicePrincipalReadOnly",
                    "Effect": "Allow",
                    "Principal": {"Service": "cloudfront.amazonaws.com"},
                    "Action": "s3:GetObject",
                    "Resource": f"{args[0]}/*",
                    "Condition": {"StringEquals": {"AWS:SourceArn": args[1]}},
                }
            ],
        }
    )
)

aws.s3.BucketPolicy(
    "site-bucket-policy",
    bucket=site_bucket.id,
    policy=bucket_policy_doc,
)

# --------------------------------------------------------------------------- #
# Outputs (consumed by the GitHub Actions workflow)                           #
# --------------------------------------------------------------------------- #
pulumi.export("bucketName", site_bucket.bucket)
pulumi.export("distributionId", distribution.id)
pulumi.export("cloudfrontDomain", distribution.domain_name)
pulumi.export("siteUrl", distribution.domain_name.apply(lambda d: f"https://{d}"))
