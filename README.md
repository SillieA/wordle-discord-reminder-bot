# WordleReminderDiscordBot

A serverless Discord bot that sends daily reminders to users who haven't completed their [Wordle](https://www.nytimes.com/games/wordle/index.html) puzzle. Built with AWS Lambda + EventBridge — costs effectively **$0/month**.

---

## Architecture

```
EventBridge (cron: 9 PM UTC daily)
        │
        ▼
  AWS Lambda (Python 3.12, arm64, 128 MB)
        │
        ▼
  Discord API v10
  (reads recent messages → sends @mention reminder)
```

---

## Cost Breakdown

| Resource | Free Tier / Cost |
|---|---|
| Lambda invocations | 1 M free/month — 1 invocation/day = ~30/month → **$0** |
| Lambda compute | 400,000 GB-s free/month — 128 MB × 10 s = 0.00125 GB-s/day → **$0** |
| EventBridge rules | 1 M events free/month → **$0** |
| **Total** | **~$0/month** |

---

## CI/CD (GitHub Actions)

Two workflows are included in `.github/workflows/`:

| Workflow | Trigger | What it does |
|---|---|---|
| `ci.yml` | Every push and pull request | Runs the full unit-test suite (`pytest`) |
| `deploy.yml` | Push to `main` | Runs tests, then deploys via Terraform |

### Required GitHub Repository Secrets

Before the deploy workflow can run you must add the following secrets to the repository (**Settings → Secrets and variables → Actions → New repository secret**):

| Secret name | Description | Example |
|---|---|---|
| `AWS_ACCESS_KEY_ID` | Access key ID for the IAM user that Terraform uses to deploy | `AKIAIOSFODNN7EXAMPLE` |
| `AWS_SECRET_ACCESS_KEY` | Corresponding IAM secret access key | `wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY` |
| `AWS_REGION` | AWS region to deploy into | `us-east-1` |
| `TF_STATE_BUCKET` | Name of an **existing** S3 bucket used to store Terraform remote state | `my-terraform-state-bucket` |
| `DISCORD_TOKEN` | Discord bot token (from the Developer Portal) | `MTExxx.xxx.xxx` |
| `CHANNEL_ID` | ID of the Discord channel where Wordle scores are posted | `1234567890123456789` |
| `USER_IDS` | Comma-separated Discord user IDs to track | `111111,222222,333333` |

> **IAM permissions required** — the IAM user behind `AWS_ACCESS_KEY_ID` needs permissions to manage Lambda functions, IAM roles, EventBridge rules, and to read/write to the `TF_STATE_BUCKET` S3 bucket.

---

## Prerequisites

- [AWS CLI](https://docs.aws.amazon.com/cli/latest/userguide/install-cliv2.html) configured (`aws configure`)
- [Terraform](https://developer.hashicorp.com/terraform/install) ≥ 1.5 (for manual deployments)
- [AWS SAM CLI](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html) (optional, for SAM-based manual deployments)
- A Discord account and server where you want the bot to post

---

## Discord Bot Setup

### 1. Create the Application

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications)
2. Click **New Application**, give it a name (e.g. "Wordle Reminder")
3. Navigate to **Bot** in the left sidebar
4. Click **Add Bot** → **Yes, do it!**
5. Under the bot's username, click **Reset Token** and copy the token — this is your `DISCORD_TOKEN`

### 2. Invite the Bot to Your Server

1. In the Developer Portal, go to **OAuth2 → URL Generator**
2. Under **Scopes**, select `bot`
3. Under **Bot Permissions**, select:
   - ✅ View Channels
   - ✅ Read Message History
   - ✅ Send Messages
4. Copy the generated URL and open it in your browser to invite the bot to your server

### 3. Get the Channel ID and User IDs

1. In Discord, go to **User Settings → Advanced** and enable **Developer Mode**
2. Right-click the channel where Wordle scores are posted → **Copy Channel ID** → `CHANNEL_ID`
3. Right-click each user's name → **Copy User ID** → add to `USER_IDS` (comma-separated)

---

## Deployment

### Option A — Terraform (recommended)

```bash
# 1. Create an S3 bucket for Terraform state (one-time)
aws s3api create-bucket --bucket my-terraform-state-bucket --region us-east-1

# 2. Initialise Terraform
cd terraform
terraform init \
  -backend-config="bucket=my-terraform-state-bucket" \
  -backend-config="region=us-east-1"

# 3. Deploy
terraform apply \
  -var="discord_token=YOUR_DISCORD_BOT_TOKEN" \
  -var="channel_id=YOUR_CHANNEL_ID" \
  -var="user_ids=USER_ID_1,USER_ID_2,USER_ID_3"
```

To destroy:

```bash
terraform destroy
```

### Option B — AWS SAM (manual)

### 1. Clone the repository

```bash
git clone https://github.com/SillieA/WordleReminderDiscordBot.git
cd WordleReminderDiscordBot
```

### 2. Build and deploy

```bash
sam build
sam deploy --guided
```

The `--guided` flag walks you through setting the required parameters:

| Parameter | Description |
|---|---|
| `DiscordToken` | Your bot token (input is hidden) |
| `ChannelId` | Discord channel ID |
| `UserIds` | Comma-separated user IDs, e.g. `111111,222222,333333` |
| `Schedule` | Cron expression (default: `cron(0 21 * * ? *)` = 9 PM UTC) |

Your answers are saved to `samconfig.toml` for future deployments. Subsequent deployments only need:

```bash
sam build && sam deploy
```

---

## Configuration

Environment variables are set via SAM parameters in `template.yaml` and passed directly to the Lambda function:

| Variable | Description |
|---|---|
| `DISCORD_TOKEN` | Bot token |
| `CHANNEL_ID` | Channel to monitor and post in |
| `USER_IDS` | Comma-separated list of user IDs to track |

To update a parameter after deployment:

```bash
sam deploy --parameter-overrides "UserIds=111,222,333,444"
```

---

## How It Works

1. **EventBridge** triggers the Lambda function once per day (default: 9 PM UTC)
2. The Lambda fetches the **last 100 messages** from the configured Discord channel
3. It looks for messages posted **today** that contain `"Wordle"` and `"/6"` (the standard Wordle share format, e.g. `Wordle 1,234 3/6` or `Wordle 1,234 X/6`)
4. It calculates the **correct puzzle number** based on the Wordle epoch (puzzle #0 = 2021-06-19)
5. Any tracked user who has **not** posted a matching message is added to the reminder list
6. If everyone has already posted, **no message is sent**
7. Otherwise, a reminder message is sent to the channel **@mentioning** only the users who haven't completed their Wordle yet

**Example reminder:**
```
🟨🟩 Wordle Reminder! 🟩🟨

@Alice @Bob

You haven't posted your Wordle #1234 result yet! Get on it! 🧩
```

---

## Customization

### Change the reminder schedule

Update the `Schedule` parameter (EventBridge cron syntax, always in UTC):

```bash
# 8 PM UTC
sam deploy --parameter-overrides "Schedule=cron(0 20 * * ? *)"
```

### Adjust detection logic

Edit `src/lambda_function.py` — the `find_wordle_completions` function controls what counts as a completed Wordle. By default it requires both `"Wordle"` and `"/6"` in the message content.

### View logs

```bash
sam logs -n WordleReminderBot --tail
```

### Remove the bot

```bash
sam delete
```

---

## Running Tests Locally

```bash
python -m pytest tests/ -v
```

No external dependencies are required — the test suite uses only the Python standard library and `unittest.mock`.

---

## Project Structure

```
wordle-discord-reminder-bot/
├── README.md
├── template.yaml               # AWS SAM template (Option B deployment)
├── samconfig.toml              # SAM deployment config
├── .gitignore
├── .github/
│   └── workflows/
│       ├── ci.yml              # Run tests on every push / PR
│       └── deploy.yml          # Terraform deploy on push to main
├── terraform/
│   ├── versions.tf             # Terraform + provider version requirements
│   ├── variables.tf            # Input variables
│   ├── main.tf                 # Lambda, IAM role, EventBridge rule
│   └── outputs.tf              # Lambda ARN / name outputs
├── src/
│   └── lambda_function.py      # Lambda handler
└── tests/
    └── test_lambda.py          # Unit tests
```
