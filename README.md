# Career Presentation — Rafael Gabriel Hueb

A responsive, interactive one-page career roadmap, deployed as a static site on
**AWS S3 + CloudFront**, with infrastructure defined in **Pulumi (Python)** and
continuous deployment via **GitHub Actions (keyless OIDC)**.

```
career-presentation/
├── index.html                 # The site (self-contained: HTML + CSS + JS)
├── assets/
│   └── profile.jpg            # Profile photo (extracted from the résumé)
├── infra/
│   ├── __main__.py            # Pulumi program (S3 + CloudFront + OIDC role)
│   ├── Pulumi.yaml            # Project + config schema
│   └── requirements.txt       # pulumi, pulumi-aws
└── .github/workflows/
    └── deploy.yml             # Provision (pulumi up) → publish → invalidate
```

## The site

- **Green pastel** palette, on-brand with the profile photo.
- **Outcome-focused**: an animated impact-metrics band (cost −30%, MTTR −40%,
  99.9% uptime, 50+ teams enabled…) precedes the timeline.
- **Interactive career roadmap**: click any role to expand the problems solved
  and the outcomes delivered.
- Scroll-reveal animations, animated counters, language proficiency bars,
  responsive nav — all vanilla JS, **no build step, no dependencies**.
- Respects `prefers-reduced-motion`.

Open `index.html` directly in a browser to preview locally.

## Architecture

```
GitHub Actions ──(OIDC, no secrets)──▶ IAM Role
      │  pulumi up · s3 sync · cloudfront invalidate
      ▼
  ┌───────────────┐        OAC (signed)        ┌────────────────────┐
  │  S3 (private)  │ ◀───────────────────────── │  CloudFront (CDN)   │ ◀── visitors (HTTPS)
  └───────────────┘                             └────────────────────┘
```

- The **S3 bucket is fully private** — public access is blocked. Only CloudFront
  can read it, via an **Origin Access Control (OAC)** and a scoped bucket policy.
- **CloudFront** terminates TLS, compresses, caches globally, and serves the site
  on its default `*.cloudfront.net` domain. `403/404 → /index.html` so unknown
  paths land on the page.
- Encryption (AES256), versioning, and least-privilege IAM are enabled by default.
- **Scalable by design**: content scales with CloudFront's global edge network;
  `priceClass` is configurable, and the whole stack is reproducible per
  environment (`dev`, `prod`, …) simply by selecting a different Pulumi stack.

## Prerequisites

- An AWS account + the [Pulumi CLI](https://www.pulumi.com/docs/install/)
- Python 3.12+
- A [Pulumi Cloud](https://app.pulumi.com/) account (free) for state — or run
  `pulumi login --local` / an S3 backend if you prefer self-managed state.

## First-time bootstrap (run once, locally)

The GitHub Actions workflow authenticates by **assuming an IAM role that Pulumi
itself creates**. To resolve that chicken-and-egg, provision the stack once from
your machine with admin credentials:

```bash
cd infra
python -m venv venv && ./venv/bin/pip install -r requirements.txt

pulumi login                       # or: pulumi login --local
pulumi stack init prod

# Optional overrides (defaults shown):
pulumi config set aws:region us-east-1
pulumi config set career-presentation:githubOrg   rafaelhueb92
pulumi config set career-presentation:githubRepo  career-presentation
pulumi config set career-presentation:githubBranch main

pulumi up
```

> **Note:** only one GitHub OIDC provider may exist per AWS account. If yours
> already exists, import it before the first `up`:
> ```bash
> pulumi import aws:iam/openIdConnectProvider:OpenIdConnectProvider \
>   github-oidc arn:aws:iam::<ACCOUNT_ID>:oidc-provider/token.actions.githubusercontent.com
> ```

Grab the outputs:

```bash
pulumi stack output deployRoleArn   # → set as GitHub secret AWS_DEPLOY_ROLE_ARN
pulumi stack output siteUrl         # → your live https://xxxx.cloudfront.net
```

## Wire up CI

In the GitHub repo → **Settings → Secrets and variables → Actions**:

| Kind     | Name                    | Value                                             |
|----------|-------------------------|---------------------------------------------------|
| Secret   | `AWS_DEPLOY_ROLE_ARN`   | `deployRoleArn` output from the bootstrap         |
| Secret   | `PULUMI_ACCESS_TOKEN`   | Pulumi Cloud access token (for state)             |
| Variable | `AWS_REGION`            | e.g. `us-east-1` (optional; defaults to us-east-1)|
| Variable | `PULUMI_STACK`          | e.g. `prod` (optional; defaults to `prod`)        |

> The deploy role trusts `repo:<org>/<repo>:ref:refs/heads/<branch>`. Keep the
> `githubOrg/githubRepo/githubBranch` config in sync with where the workflow runs.

## Deploy

Push to `main` (or run the workflow manually). The pipeline will:

1. Assume the deploy role via OIDC (no stored keys).
2. `pulumi up` — converge the infrastructure.
3. `s3 sync` assets with a 1-year immutable cache; upload `index.html` with
   `must-revalidate`.
4. Invalidate the CloudFront cache (`/*`).
5. Print the live URL in the job summary.

## Cost

Idle cost is effectively zero (S3 storage of a few hundred KB). CloudFront +
S3 requests fall well within the AWS Free Tier for a personal site.
