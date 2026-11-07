# Keep the code hidden, keep the free runners

A **public** repository gets free standard GitHub runners. A public repository also
shows every file in it. This folder is the way to have both: the code stays in the
private repository, and only one file goes public.

```text
private:  Nishgamerrz/Ai-rant          <- tools/, users/, prompts, everything
public:   <you>/roblox-short-runner    <- .github/workflows/main.yml ONLY
```

The public file is `runner/main.yml` from this folder. It checks the private
repository out into a folder called `src/` using a read-only token, then runs the
same steps as the private workflow from inside `src/`, so the finished MP4 is
identical.

`python3 runner/make_runner_workflow.py` regenerates it whenever
`.github/workflows/main.yml` changes. Never edit `runner/main.yml` by hand.

---

## Setup (about five minutes, once)

### 1. Make the private repository private again

`Ai-rant` -> **Settings** -> scroll to **Danger Zone** -> **Change repository
visibility** -> **Change to private** -> type the repository name.

> Anything that was public while the repository was open should be treated as
> already seen. There are no API keys in the tree (checked), and your
> `GEMINI_API_KEY` secret was never exposed - secrets are not published by making
> a repository public.

### 2. Create the public runner repository

New repository -> name it `roblox-short-runner` -> **Public**
-> do **not** add a README, `.gitignore` or licence.

### 3. Add the one file

On the empty repository: **Add file** -> **Create new file** -> path:

```text
.github/workflows/main.yml
```

Paste the whole of [`runner/main.yml`](main.yml) from this folder and commit.
That is the only file the public repository will ever have.

### 4. Create a read-only token for the private repository

GitHub -> **Settings** -> **Developer settings** -> **Personal access tokens** ->
**Fine-grained tokens** -> **Generate new token**:

| Field | Value |
|---|---|
| Resource owner | `Nishgamerrz` (the owner of `Ai-rant`) |
| Repository access | **Only select repositories** -> `Ai-rant` |
| Permissions -> Repository permissions -> **Contents** | **Read-only** |
| Everything else | No access |
| Expiration | 90 days (repeat this step when it expires) |

Copy the token.

### 5. Put the secrets on the **public** repository

The public repository is a different repository, so it needs its own copies.
Public repository -> **Settings** -> **Secrets and variables** -> **Actions**:

| Type | Name | Value |
|---|---|---|
| Secret | `SOURCE_TOKEN` | the read-only token from step 4 |
| Secret | `GEMINI_API_KEY` | same free key you already use (optional) |
| Variable | `GEMINI_MODEL` | `gemini-2.5-flash` (optional) |

`SOURCE_TOKEN` is only used to fetch the private code. It cannot push, cannot
read other repositories, and cannot see secrets.

### 6. Run it from the public repository

**Actions** -> **Generate Furnished Roblox-Style Short (MP4)** -> **Run workflow**
-> fill in the story topic, usernames, length, preset, and start.

You can also disable the workflow in the private repository (Actions -> the
workflow -> `...` -> **Disable workflow**) so a stray click cannot burn minutes.

---

## What is still public

Be clear about this part:

| Item | Public? | Why |
|---|---|---|
| `tools/`, `users/`, prompts, history | **No** | stays in the private repository |
| `.github/workflows/main.yml` (the shell) | **Yes** | a workflow only runs from the repository it lives in |
| Run logs of the public repository | **Yes** | that is how you watch the run |
| Run artifacts (MP4, ZIP, PDF) | **Yes** | uploaded to the public repository |
| Secrets (`SOURCE_TOKEN`, `GEMINI_API_KEY`) | **No** | never exposed, never passed to forks |

If the finished videos must stay private too, either delete the artifacts after
downloading them, or set a very short `retention-days` on the two upload steps.
Tell me and I will add that.

## Alternatives, if this is more setup than you want

1. **Pay for private minutes** - keep everything private, fix the billing block
   (payment method or spending limit) and run the workflow in the private
   repository as before. A 1h20 run costs about 80 minutes.
2. **Stay public** - nothing to do, but the code is readable by anyone.
3. **Wait for the monthly reset** - free private minutes refill, nothing runs until
   then.

## Checks

`tests/test_runner_shell.py` regenerates the shell and fails if `runner/main.yml`
has drifted from `.github/workflows/main.yml`, if any step would run outside
`src/`, or if the shell ever grows a second file.
