# openQA Review Assistant

An expert Gemini CLI skill designed for SUSE QA Engineers. This agent uses scripts that provide information from openQA, SMELT, GitHub and other places, categorizes test failures, parses GitHub commit history, and cross-references with historical openQA jobs to diagnose test failures.

## Prerequisites

* [Gemini CLI](https://github.com/google/gemini-cli) installed and authenticated.
* Python 3.8+ 
* A GitHub Personal Access Token (Classic or Fine-Grained) with repository read access. Not strictly needed, but the skill will probably reach the unauthenticated limits quickly if it's not added.

## Setup Instructions

### 1. Clone the Repository
Clone this repository to your local machine and navigate into the project root:

```bash
git clone <your_repo_url> openqa-review-assistant
cd openqa-review-assistant
```

### 2. Configure Credentials
The agent needs a GitHub token to parse commit histories and trace code paths. 

Either:

**A. Configure the env variable**

`export GITHUB_TOKEN="<YOUR_GH_TOKEN>"`

**OR**

**B. Add it to the creds.conf file**

1. Copy the example configuration file:
```bash
cp credentials/creds.conf.example credentials/creds.conf
```
2. Edit `credentials/creds.conf` and paste your GitHub token:
```env
GITHUB_TOKEN=ghp_your_token_here
```
*(Note: Do not commit `creds.conf` to version control. It is ignored via `.gitignore` by default).*

### 3. Apply the Strict Execution Policy
This skill operates with a highly restricted security policy. To prevent the LLM from executing arbitrary shell commands or reading unintended files on your machine, you must apply the project's specific `policy.toml`.

A helper script is provided to safely swap your default Gemini CLI policy with the strict project policy:

```bash
# Activate the strict skill policy
./toggle_policy.sh
```
*This script backs up your existing policy. You can - and should, once you are finished with using the skill - run `./toggle_policy.sh` again at any time to restore your normal settings.*

If you do not want to use the script, you can easily do this manually - simply rename your policy file in `~/.gemini/policies/` and replace it with the provided policy file from this project's `.gemini/policies/policy.toml`. Change back once finished with the script execution.

---

## Usage

Always run the Gemini CLI from the **project root directory** so the agent can correctly locate the `/scripts` folder.

1. Start the Gemini CLI in interactive mode:
```bash
gemini
```

2. Activate the skill and ask it to review an openQA job:
```text
> Use the openQA Review Assistant skill. Triage job 1234567.
```

or for easier execution, use the command:
```text
/review 1234567
```

You can optionally provide additional context after invoking the command for the agent to take into account:

```text
/review 1234567 - I think this could be a regression of the kernel-default update
```

---

## Cleanup

Once you are done working with the agent, remember to restore your standard Gemini CLI permissions so you aren't restricted by the openQA security policy on other projects:

```bash
./toggle_policy.sh
```