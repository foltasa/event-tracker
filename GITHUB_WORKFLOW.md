# GitHub Workflow Guide - Universal Best Practices

**Version**: 2.0
**Last Updated**: 2025-10-18
**Purpose**: Reusable GitHub workflow guide for professional development across all projects

---

## Table of Contents

1. [Philosophy & Principles](#1-philosophy--principles)
2. [Initial Repository Setup](#2-initial-repository-setup)
3. [Branch Strategy](#3-branch-strategy)
4. [Commit Standards](#4-commit-standards)
5. [Issue Management](#5-issue-management)
6. [Pull Request Workflow](#6-pull-request-workflow)
7. [Milestone & Project Planning](#7-milestone--project-planning)
8. [Label System](#8-label-system)
9. [Code Review Process](#9-code-review-process)
10. [GitHub CLI Essentials](#10-github-cli-essentials)
11. [Automation & CI/CD](#11-automation--cicd)
12. [Team Collaboration](#12-team-collaboration)
13. [Troubleshooting](#13-troubleshooting)

---

## 1. Philosophy & Principles

### Core Values

1. **Clarity over Brevity**: Clear communication beats short messages
2. **Traceability**: Every change should be traceable to an issue or requirement
3. **Reversibility**: All changes should be reversible (avoid force push)
4. **Collaboration**: Assume your code will be read by others (including future you)
5. **Automation**: Automate repetitive tasks, document manual processes

### Key Concepts

- **Main branch is sacred**: Always production-ready, protected
- **Feature branches are temporary**: Delete after merge
- **Issues track work**: Every significant change starts with an issue
- **PRs enable review**: Never commit directly to main
- **Milestones organize releases**: Group related work logically

---

## 2. Initial Repository Setup

### Step 1: Repository Initialization

```bash
# Clone or initialize repository
git clone <repository-url>
cd <repository-name>

# Or create new repository
git init
git branch -M main
```

### Step 2: Configure Git Identity

```bash
# Set user identity (required for commits)
git config user.name "Your Name"
git config user.email "your.email@example.com"

# Optional: Configure global settings
git config --global core.editor "vim"
git config --global pull.rebase false
git config --global init.defaultBranch main
```

### Step 3: Create GitHub Infrastructure

Create `.github/` directory structure:

```
.github/
├── ISSUE_TEMPLATE/
│   ├── bug_report.md
│   ├── feature_request.md
│   └── documentation.md
├── pull_request_template.md
└── workflows/
    └── ci.yml (if using CI/CD)
```

**Bug Report Template** (`.github/ISSUE_TEMPLATE/bug_report.md`):
```markdown
---
name: Bug Report
about: Report a bug or issue
title: '[BUG] '
labels: bug
assignees: ''
---

## Bug Description
<!-- Clear description of what's broken -->

## Steps to Reproduce
1. Step 1
2. Step 2
3. See error

## Expected Behavior
<!-- What should happen -->

## Actual Behavior
<!-- What actually happens -->

## Environment
- OS:
- Version:
- Other relevant info:

## Error Logs
\`\`\`
Paste error logs here
\`\`\`

## Additional Context
<!-- Screenshots, related issues, etc. -->
```

**Feature Request Template** (`.github/ISSUE_TEMPLATE/feature_request.md`):
```markdown
---
name: Feature Request
about: Suggest a new feature or enhancement
title: '[FEATURE] '
labels: enhancement
assignees: ''
---

## Feature Summary
<!-- Brief description of the feature -->

## Use Case
<!-- Why is this feature needed? Who benefits? -->

## Proposed Solution
<!-- How should this work? -->

## Alternatives Considered
<!-- What other approaches did you consider? -->

## Acceptance Criteria
- [ ] Criterion 1
- [ ] Criterion 2
- [ ] Criterion 3

## Priority
<!-- Low / Medium / High / Critical -->

## Additional Context
<!-- Mockups, references, examples -->
```

**Pull Request Template** (`.github/pull_request_template.md`):
```markdown
## Summary
<!-- What does this PR do? -->

## Related Issues
<!-- Link to issues: Closes #123, Relates to #456 -->

## Changes Made
- Change 1
- Change 2
- Change 3

## Testing
- [ ] Unit tests added/updated
- [ ] Integration tests pass
- [ ] Manual testing completed

## Documentation
- [ ] Code comments added
- [ ] README updated (if needed)
- [ ] API docs updated (if needed)

## Checklist
- [ ] Code follows project style guide
- [ ] No console warnings or errors
- [ ] Branch is up to date with main
- [ ] Self-reviewed the code
- [ ] Breaking changes documented

## Screenshots (if applicable)
<!-- Add screenshots for UI changes -->
```

### Step 4: Set Default Branch

```bash
# Via GitHub CLI
gh repo edit --default-branch main

# Or via Git (rename master to main)
git branch -m master main
git push -u origin main
gh repo edit --default-branch main
git push origin --delete master
```

### Step 5: Configure Branch Protection

```bash
# Via GitHub CLI (recommended)
gh api repos/{owner}/{repo}/branches/main/protection -X PUT -F required_pull_request_reviews='{"required_approving_review_count":1}' -F enforce_admins=true -F required_status_checks=null

# Or via GitHub Web UI:
# Settings → Branches → Add rule
```

**Recommended Protection Rules**:
- ✅ Require a pull request before merging
- ✅ Require approvals: 1+ (or 0 for solo projects)
- ✅ Dismiss stale pull request approvals when new commits are pushed
- ✅ Require branches to be up to date before merging
- ✅ Require conversation resolution before merging
- ❌ Do not bypass settings (unless admin override needed)

---

## 3. Branch Strategy

### GitHub Flow (Recommended)

Simple, effective workflow for continuous deployment:

```
main (protected)
  ├── feature/user-authentication
  ├── fix/login-bug
  ├── refactor/database-schema
  └── docs/api-documentation
```

### Branch Naming Convention

**Format**: `<type>/<short-description>`

**Types**:
- `feature/` - New features or enhancements
- `fix/` - Bug fixes
- `refactor/` - Code refactoring (no behavior change)
- `docs/` - Documentation only
- `test/` - Test additions or fixes
- `chore/` - Maintenance tasks (dependencies, config, tooling)
- `hotfix/` - Urgent production fixes

**Examples**:
```bash
feature/user-dashboard
fix/payment-validation-error
refactor/api-error-handling
docs/installation-guide
test/integration-test-suite
chore/update-dependencies
hotfix/critical-security-patch
```

**Rules**:
- Use lowercase with hyphens (kebab-case)
- Keep names short but descriptive
- Avoid special characters except hyphens
- Maximum 50 characters

### Branch Lifecycle

**1. Create Branch**:
```bash
# Always start from latest main
git checkout main
git pull origin main

# Create and switch to new branch
git checkout -b feature/your-feature-name
```

**2. Work on Branch**:
```bash
# Make changes, commit regularly
git add .
git commit -m "type(scope): description"

# Push to remote
git push -u origin feature/your-feature-name
```

**3. Keep Branch Updated**:
```bash
# Sync with main regularly
git checkout main
git pull origin main
git checkout feature/your-feature-name
git merge main

# Or use rebase (cleaner history, but advanced)
git rebase main
```

**4. Create Pull Request**:
```bash
# Via GitHub CLI
gh pr create --title "Feature: Your feature name" --body "Description"

# Or push and use GitHub web UI
git push -u origin feature/your-feature-name
# Visit GitHub → Compare & pull request
```

**5. Delete Branch After Merge**:
```bash
# Delete local branch
git checkout main
git branch -d feature/your-feature-name

# Delete remote branch (usually auto-deleted via PR settings)
git push origin --delete feature/your-feature-name
```

### Long-Lived Branches to Avoid

❌ **Anti-patterns**:
- Multiple long-lived feature branches
- Development/staging branches (use tags instead)
- Personal branches (use forks for open source)
- Unmaintained branches

✅ **Exceptions**:
- `main` - Production code
- `gh-pages` - GitHub Pages hosting (auto-managed)

---

## 4. Commit Standards

### Conventional Commits Format

**Structure**: `<type>(<scope>): <subject>`

```
feat(auth): add OAuth2 login support

- Implemented OAuth2 provider integration
- Added login/logout endpoints
- Updated user model for OAuth tokens

Closes #123
```

### Commit Types

| Type | Description | Example |
|------|-------------|---------|
| `feat` | New feature | `feat(api): add user search endpoint` |
| `fix` | Bug fix | `fix(auth): resolve token expiration issue` |
| `docs` | Documentation only | `docs(readme): update installation steps` |
| `style` | Code style changes (formatting, semicolons) | `style(components): fix linting errors` |
| `refactor` | Code refactoring (no behavior change) | `refactor(utils): simplify error handling` |
| `perf` | Performance improvement | `perf(db): add index on user_id column` |
| `test` | Adding or updating tests | `test(auth): add unit tests for login` |
| `chore` | Maintenance tasks | `chore(deps): update dependencies` |
| `ci` | CI/CD changes | `ci(github): add automated testing workflow` |
| `build` | Build system changes | `build(webpack): optimize production build` |
| `revert` | Revert previous commit | `revert: undo "feat(api): add endpoint"` |

### Commit Message Guidelines

**Subject Line** (first line):
- Start with type and optional scope
- Use imperative mood ("add" not "added" or "adds")
- No period at the end
- Maximum 72 characters
- Capitalize first letter after colon

**Body** (optional, after blank line):
- Explain what and why, not how
- Wrap at 72 characters
- Use bullet points for multiple changes
- Reference issues with `Closes #123` or `Relates to #456`

**Examples**:

```bash
# Good commits
git commit -m "feat(users): add email verification flow"

git commit -m "fix(api): handle null response from database

- Added null check before processing
- Return 404 status code instead of 500
- Updated error messages for clarity

Closes #234"

git commit -m "docs(contributing): add code of conduct"

git commit -m "refactor(auth): extract JWT logic to utility module"

# Bad commits (avoid these)
git commit -m "update"
git commit -m "fix bug"
git commit -m "WIP"
git commit -m "asdfasdf"
git commit -m "Fixed the thing that was broken yesterday"
```

### Multi-Author Commits

When pair programming or collaborating:

```bash
git commit -m "feat(api): add search functionality

Co-Authored-By: Partner Name <partner@email.com>"
```

### Commit Frequency

**Best Practices**:
- Commit logically complete units of work
- Commit frequently (multiple times per day)
- Each commit should be atomic (one logical change)
- Don't commit half-finished features to shared branches

**When to Commit**:
- ✅ Feature complete and tested
- ✅ Bug fix verified
- ✅ Refactoring passes tests
- ✅ Documentation updated
- ❌ Broken code
- ❌ Half-implemented features
- ❌ "Work in progress" on shared branches

---

## 5. Issue Management

### Issue Lifecycle

```
Open → In Progress → Review/Testing → Closed
```

### Creating Issues

**1. Choose Template**:
- Bug Report: For defects and problems
- Feature Request: For new functionality
- Documentation: For doc improvements
- Custom: For other work

**2. Write Clear Titles**:
```bash
# Good
[BUG] Login fails with OAuth provider
[FEATURE] Add dark mode toggle
[DOCS] Update API authentication guide

# Bad
Bug
New feature
Update docs
```

**3. Complete All Sections**:
- Description: What needs to be done?
- Acceptance Criteria: How do we know it's done?
- Context: Why is this needed?
- Resources: Links, references, examples

**4. Assign Metadata**:
- **Labels**: Categorize the issue (bug, enhancement, documentation)
- **Milestone**: Link to release or phase
- **Assignees**: Who will work on this?
- **Projects**: Link to project board (optional)

### Issue Linking

**In Commits**:
```bash
# Close issue automatically when PR merges
git commit -m "fix(auth): resolve token issue

Closes #123"

# Reference without closing
git commit -m "feat(api): add endpoint

Relates to #456
Part of #789"
```

**Closing Keywords** (case-insensitive):
- `Closes #123`
- `Fixes #123`
- `Resolves #123`
- `Closes: #123, #456`

**In Pull Requests**:
```markdown
## Related Issues
Closes #123
Relates to #456, #789
```

### Issue Labels

**Standard Label Categories**:

**Type** (what kind of work):
- `bug` - Something isn't working
- `enhancement` - New feature or request
- `documentation` - Documentation improvements
- `question` - Further information requested
- `duplicate` - This issue already exists
- `invalid` - This doesn't seem right
- `wontfix` - This will not be worked on

**Priority** (how urgent):
- `critical` - Blocking, must fix immediately
- `high-priority` - Should be addressed soon
- `medium-priority` - Normal priority
- `low-priority` - Nice to have

**Status** (current state):
- `in-progress` - Actively being worked on
- `needs-review` - Awaiting code review
- `blocked` - Waiting on external dependency
- `ready` - Ready to be worked on

**Area** (what part of codebase):
- `backend` - Backend/API work
- `frontend` - UI/UX work
- `database` - Database schema/queries
- `testing` - Test-related work
- `ci-cd` - CI/CD pipeline

### Issue Best Practices

✅ **Do**:
- Create issues before starting work
- Link commits and PRs to issues
- Update issue status regularly
- Close issues when work is complete
- Use labels consistently

❌ **Don't**:
- Leave issues open indefinitely
- Create duplicate issues (search first)
- Use issues for discussions (use Discussions instead)
- Assign too many labels (3-5 is ideal)

---

## 6. Pull Request Workflow

### Creating a Pull Request

**Step 1: Prepare Your Branch**
```bash
# Ensure branch is up to date
git checkout main
git pull origin main
git checkout feature/your-feature
git merge main

# Run tests locally
npm test  # or your test command

# Push latest changes
git push origin feature/your-feature
```

**Step 2: Create PR**
```bash
# Via GitHub CLI (recommended)
gh pr create --title "feat(feature): add new capability" \
  --body "$(cat <<'EOF'
## Summary
Description of what this PR does.

## Related Issues
Closes #123

## Changes Made
- Change 1
- Change 2

## Testing
- [x] Unit tests pass
- [x] Integration tests pass
- [x] Manual testing completed

## Screenshots
(if applicable)
EOF
)"

# Or via GitHub Web UI
# Push branch → GitHub shows "Compare & pull request" button
```

**Step 3: Fill Out PR Template**
- Complete all sections
- Link related issues
- Explain the "why" not just the "what"
- Add screenshots for UI changes
- Mark draft if not ready for review

**Step 4: Self-Review**
Before requesting review:
- ✅ Read through all changes in GitHub
- ✅ Check for debug code, console.logs
- ✅ Verify tests pass
- ✅ Ensure no merge conflicts
- ✅ Add inline comments for complex logic

### PR Checklist

**Before Creating PR**:
- [ ] Branch is up to date with main
- [ ] All tests pass locally
- [ ] Code follows project style guide
- [ ] No console errors or warnings
- [ ] Documentation updated (if needed)
- [ ] Commit messages follow conventions
- [ ] Self-reviewed all changes

**During Review**:
- [ ] Respond to all comments
- [ ] Make requested changes
- [ ] Mark conversations as resolved
- [ ] Keep PR updated with main
- [ ] Ensure CI/CD passes

**Before Merging**:
- [ ] All comments addressed
- [ ] All checks pass (CI, tests, linting)
- [ ] Required approvals obtained
- [ ] No merge conflicts
- [ ] Final self-review completed

### PR Review Process

**For Reviewers**:
1. **Understand the context**: Read issue, PR description
2. **Check functionality**: Does it work as intended?
3. **Review code quality**: Is it maintainable?
4. **Test coverage**: Are there adequate tests?
5. **Performance**: Any performance concerns?
6. **Security**: Any security issues?
7. **Documentation**: Is it well-documented?

**Review Comments**:
- **Blocking**: Must be fixed before merge
- **Non-blocking**: Suggestions for improvement
- **Nitpick**: Minor style/preference issues
- **Question**: Clarification needed

**Comment Prefixes**:
```
[BLOCKING] This will cause a memory leak
[SUGGESTION] Consider using a Map instead
[NITPICK] Missing space after comma
[QUESTION] Why did you choose this approach?
[PRAISE] Great solution!
```

### PR Merge Strategies

**1. Merge Commit** (default):
- Preserves full history
- Creates merge commit
- Best for: Feature branches with multiple commits
```bash
git merge --no-ff feature/your-feature
```

**2. Squash and Merge**:
- Combines all commits into one
- Clean history on main
- Best for: Many small commits, WIP commits
```bash
gh pr merge --squash
```

**3. Rebase and Merge**:
- Applies commits on top of main
- Linear history
- Best for: Clean commit history already
```bash
gh pr merge --rebase
```

**Recommendation**: Use **Squash and Merge** for most feature branches.

### PR Troubleshooting

**Merge Conflicts**:
```bash
# Update your branch with main
git checkout feature/your-feature
git fetch origin
git merge origin/main

# Resolve conflicts in your editor
# Look for <<<<<<< HEAD markers

# Mark as resolved
git add .
git commit -m "chore: resolve merge conflicts"
git push origin feature/your-feature
```

**Failed CI Checks**:
1. Review error logs in GitHub Actions
2. Reproduce issue locally
3. Fix the issue
4. Commit and push fix
5. CI will re-run automatically

**Stale Branch**:
```bash
# Rebase on latest main
git checkout feature/your-feature
git fetch origin
git rebase origin/main

# If conflicts, resolve and continue
git add .
git rebase --continue

# Force push (only for feature branches!)
git push --force-with-lease origin feature/your-feature
```

---

## 7. Milestone & Project Planning

### Milestone Strategy

**Purpose**: Group related issues into releases or phases.

**Milestone Structure**:
```
Phase 1 - Foundation (Closed)
├── Due: 2025-06-30
├── Description: Core architecture and setup
└── Issues: #1, #2, #3, #4

Phase 2 - Features (In Progress)
├── Due: 2025-08-31
├── Description: Primary feature implementation
└── Issues: #5, #6, #7

Phase 3 - Polish (Open)
├── Due: 2025-10-31
├── Description: UX improvements and optimization
└── Issues: #8, #9, #10
```

### Creating Milestones

**Via GitHub CLI**:
```bash
# Create milestone
gh api repos/{owner}/{repo}/milestones -X POST \
  -f title="Phase 1 - Foundation" \
  -f description="Core architecture and setup" \
  -f due_on="2025-06-30T23:59:59Z" \
  -f state="open"

# Close milestone
gh api repos/{owner}/{repo}/milestones/{number} -X PATCH \
  -f state="closed"
```

**Via GitHub Web UI**:
1. Issues → Milestones → New milestone
2. Fill in: Title, Description, Due date
3. Click Create milestone

### Milestone Best Practices

**Naming**:
- Use semantic versioning: `v1.0.0`, `v1.1.0`, `v2.0.0`
- Or phase-based: `Phase 1 - Setup`, `Phase 2 - Features`
- Or date-based: `Q3 2025 Release`, `Sprint 23`

**Planning**:
- 5-15 issues per milestone (manageable scope)
- Set realistic due dates (add buffer time)
- Review progress weekly
- Adjust scope if falling behind

**Tracking**:
```bash
# View milestone progress
gh api repos/{owner}/{repo}/milestones | grep -A5 "title"

# List issues in milestone
gh issue list --milestone "Phase 1 - Foundation"
```

### Project Boards (Optional)

For Kanban-style workflow:

**Columns**:
1. **Backlog** - Not yet prioritized
2. **To Do** - Prioritized, ready to start
3. **In Progress** - Currently being worked on
4. **In Review** - PR open, awaiting review
5. **Done** - Completed and merged

**Automation**:
- Auto-move issues to "In Progress" when PR created
- Auto-move to "Done" when PR merged
- Auto-close issues when moved to "Done"

---

## 8. Label System

### Comprehensive Label Categories

#### Type Labels (What kind of work)

| Label | Color | Description |
|-------|-------|-------------|
| `bug` | `#d73a4a` | Something isn't working |
| `enhancement` | `#a2eeef` | New feature or request |
| `documentation` | `#0075ca` | Documentation improvements |
| `refactor` | `#e99695` | Code refactoring |
| `performance` | `#fef2c0` | Performance optimization |
| `security` | `#ee0701` | Security-related work |
| `testing` | `#c5def5` | Testing and QA |

#### Priority Labels

| Label | Color | Description |
|-------|-------|-------------|
| `critical` | `#b60205` | Blocking, must fix immediately |
| `high-priority` | `#e99695` | Should be addressed soon |
| `medium-priority` | `#fbca04` | Normal priority |
| `low-priority` | `#0e8a16` | Nice to have |

#### Status Labels

| Label | Color | Description |
|-------|-------|-------------|
| `in-progress` | `#fef2c0` | Actively being worked on |
| `blocked` | `#d93f0b` | Waiting on dependency |
| `needs-review` | `#fbca04` | Ready for code review |
| `wontfix` | `#ffffff` | Will not be worked on |
| `duplicate` | `#cfd3d7` | This issue already exists |

#### Area Labels (Where in codebase)

| Label | Color | Description |
|-------|-------|-------------|
| `backend` | `#1d76db` | Backend/API work |
| `frontend` | `#5319e7` | UI/UX work |
| `database` | `#bfd4f2` | Database schema/queries |
| `ci-cd` | `#0e8a16` | CI/CD pipeline |
| `infrastructure` | `#bfdadc` | Infrastructure/tooling |

### Creating Labels

**Bulk Label Creation Script**:
```bash
#!/bin/bash

# Create type labels
gh label create "bug" --color "d73a4a" --description "Something isn't working" --force
gh label create "enhancement" --color "a2eeef" --description "New feature or request" --force
gh label create "documentation" --color "0075ca" --description "Documentation improvements" --force

# Create priority labels
gh label create "critical" --color "b60205" --description "Blocking, must fix immediately" --force
gh label create "high-priority" --color "e99695" --description "Should be addressed soon" --force

# Create status labels
gh label create "in-progress" --color "fef2c0" --description "Actively being worked on" --force
gh label create "blocked" --color "d93f0b" --description "Waiting on dependency" --force

# Create area labels
gh label create "backend" --color "1d76db" --description "Backend/API work" --force
gh label create "frontend" --color "5319e7" --description "UI/UX work" --force
```

**List All Labels**:
```bash
gh label list
```

---

## 9. Code Review Process

### Review Checklist

**Functionality**:
- [ ] Does the code do what it's supposed to do?
- [ ] Are edge cases handled?
- [ ] Are error cases handled gracefully?
- [ ] Does it work on all supported platforms?

**Code Quality**:
- [ ] Is the code readable and maintainable?
- [ ] Are variable/function names clear?
- [ ] Is there unnecessary complexity?
- [ ] Is there duplicate code?
- [ ] Does it follow project conventions?

**Testing**:
- [ ] Are there adequate unit tests?
- [ ] Do tests cover edge cases?
- [ ] Are tests maintainable?
- [ ] Do all tests pass?

**Performance**:
- [ ] Are there any obvious performance issues?
- [ ] Are queries/loops optimized?
- [ ] Is caching used appropriately?
- [ ] Are large files handled efficiently?

**Security**:
- [ ] Are inputs validated?
- [ ] Are security best practices followed?
- [ ] Are secrets properly handled?
- [ ] Is sensitive data encrypted?

**Documentation**:
- [ ] Are complex parts commented?
- [ ] Is public API documented?
- [ ] Are breaking changes documented?
- [ ] Is README updated if needed?

### Review Etiquette

**For Reviewers**:
- ✅ Be kind and constructive
- ✅ Explain why, not just what
- ✅ Praise good solutions
- ✅ Suggest alternatives
- ✅ Ask questions
- ❌ Demand changes without explanation
- ❌ Be condescending
- ❌ Nitpick excessively

**For Authors**:
- ✅ Welcome feedback
- ✅ Explain your reasoning
- ✅ Ask for clarification
- ✅ Make requested changes promptly
- ❌ Take criticism personally
- ❌ Ignore feedback
- ❌ Argue unnecessarily

### Review Comments

**Good Review Comments**:
```
[BLOCKING] This query could cause a full table scan.
Consider adding an index on user_id column.

[SUGGESTION] You could simplify this with the `.filter()` method:
```javascript
return items.filter(item => item.active);
```

[QUESTION] Why did you choose to use recursion here?
I'm worried about stack overflow for large inputs.

[PRAISE] Love this pattern! Much cleaner than the previous implementation.

[NITPICK] Missing semicolon on line 45
```

**Bad Review Comments**:
```
❌ This is wrong.
❌ Why would you do it this way?
❌ Rewrite this.
❌ LGTM (without actually reviewing)
```

---

## 10. GitHub CLI Essentials

### Installation

```bash
# macOS
brew install gh

# Windows
winget install GitHub.cli

# Linux (Debian/Ubuntu)
curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | sudo dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null
sudo apt update
sudo apt install gh
```

### Authentication

```bash
# Login to GitHub
gh auth login

# Check auth status
gh auth status

# Logout
gh auth logout
```

### Common Commands

#### Repository Operations

```bash
# Clone repository
gh repo clone owner/repo

# Create new repository
gh repo create my-repo --public --source=. --remote=origin

# View repository
gh repo view

# Edit repository settings
gh repo edit --default-branch main
```

#### Issue Operations

```bash
# Create issue
gh issue create --title "Bug: Login fails" --body "Description" --label "bug"

# List issues
gh issue list
gh issue list --milestone "Phase 1"
gh issue list --label "bug"
gh issue list --assignee "@me"

# View issue
gh issue view 123

# Close issue
gh issue close 123

# Reopen issue
gh issue reopen 123
```

#### Pull Request Operations

```bash
# Create PR
gh pr create --title "feat: Add feature" --body "Description"

# List PRs
gh pr list
gh pr list --state all
gh pr list --author "@me"

# View PR
gh pr view 123

# Checkout PR locally
gh pr checkout 123

# Review PR
gh pr review 123 --approve
gh pr review 123 --request-changes --body "Needs fixes"
gh pr review 123 --comment --body "LGTM"

# Merge PR
gh pr merge 123 --squash
gh pr merge 123 --merge
gh pr merge 123 --rebase

# Close PR without merging
gh pr close 123
```

#### Workflow Operations

```bash
# List workflows
gh workflow list

# Run workflow
gh workflow run ci.yml

# View workflow runs
gh run list

# View run details
gh run view 123456

# Watch run in real-time
gh run watch 123456
```

### Advanced CLI Usage

**Batch Operations**:
```bash
# Close all stale issues
gh issue list --label "stale" --json number --jq '.[].number' | xargs -I {} gh issue close {}

# Approve all PRs from trusted author
gh pr list --author "trusted-dev" --json number --jq '.[].number' | xargs -I {} gh pr review {} --approve
```

**Scripting**:
```bash
#!/bin/bash
# Create multiple labels
labels=("bug:d73a4a" "enhancement:a2eeef" "docs:0075ca")
for label_data in "${labels[@]}"; do
  IFS=':' read -r label color <<< "$label_data"
  gh label create "$label" --color "$color" --force
done
```

---

## 11. Automation & CI/CD

### GitHub Actions Setup

**Basic CI Workflow** (`.github/workflows/ci.yml`):
```yaml
name: CI

on:
  push:
    branches: [ main ]
  pull_request:
    branches: [ main ]

jobs:
  test:
    runs-on: ubuntu-latest

    steps:
    - uses: actions/checkout@v3

    - name: Setup Node.js
      uses: actions/setup-node@v3
      with:
        node-version: '18'
        cache: 'npm'

    - name: Install dependencies
      run: npm ci

    - name: Run linter
      run: npm run lint

    - name: Run tests
      run: npm test

    - name: Build
      run: npm run build
```

### Auto-Label PRs

```yaml
name: Auto Label

on:
  pull_request:
    types: [opened]

jobs:
  label:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/labeler@v4
        with:
          repo-token: ${{ secrets.GITHUB_TOKEN }}
```

**Configuration** (`.github/labeler.yml`):
```yaml
documentation:
  - 'docs/**/*'
  - '**/*.md'

frontend:
  - 'src/components/**/*'
  - 'src/pages/**/*'

backend:
  - 'src/api/**/*'
  - 'src/services/**/*'

tests:
  - 'tests/**/*'
  - '**/*.test.js'
```

### Auto-Close Stale Issues

```yaml
name: Close Stale Issues

on:
  schedule:
    - cron: '0 0 * * *'  # Daily

jobs:
  stale:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/stale@v8
        with:
          stale-issue-message: 'This issue is stale. Please update or it will be closed.'
          close-issue-message: 'Closed due to inactivity.'
          days-before-stale: 60
          days-before-close: 7
          exempt-issue-labels: 'pinned,blocked'
```

---

## 12. Team Collaboration

### Team Workflows

**Small Team (2-5 developers)**:
- Feature branches for all work
- 1 required approval
- Squash and merge
- Weekly syncs

**Medium Team (6-15 developers)**:
- Feature branches + release branches
- 2 required approvals
- Code owners for critical paths
- Daily standups

**Large Team (16+ developers)**:
- Trunk-based development
- Feature flags for incomplete work
- Monorepo with CODEOWNERS
- Automated testing required

### CODEOWNERS File

**Setup** (`.github/CODEOWNERS`):
```
# Global owners
* @team-leads

# Backend team
/src/api/ @backend-team
/src/services/ @backend-team

# Frontend team
/src/components/ @frontend-team
/src/pages/ @frontend-team

# DevOps team
/.github/ @devops-team
/docker/ @devops-team

# Documentation
/docs/ @tech-writers
```

**Benefits**:
- Auto-request reviews from code owners
- Enforce approval from specific teams
- Clear ownership of code areas

### Communication Practices

**In Issues**:
- Keep discussion focused on the issue
- Move off-topic discussions to separate issues
- Use @mentions to notify specific people
- Close resolved issues promptly

**In PRs**:
- Respond to all comments
- Mark conversations as resolved
- Update PR description as scope changes
- Keep reviewers informed of major changes

**In Commits**:
- Write clear commit messages
- Reference issues consistently
- Co-author when appropriate

---

## 13. Troubleshooting

### Common Git Problems

**Forgot to Pull Before Committing**:
```bash
# If no conflicts
git pull --rebase origin main

# If conflicts
git pull origin main
# Resolve conflicts
git add .
git commit -m "chore: merge main"
```

**Committed to Wrong Branch**:
```bash
# Move commits to new branch
git branch feature/correct-branch
git reset --hard origin/main
git checkout feature/correct-branch
```

**Need to Undo Last Commit**:
```bash
# Keep changes, undo commit
git reset --soft HEAD~1

# Discard changes and commit
git reset --hard HEAD~1
```

**Pushed Sensitive Data**:
```bash
# Use BFG Repo-Cleaner
brew install bfg
bfg --delete-files secrets.txt
git push --force
```

**Branch Diverged from Remote**:
```bash
# Force update remote (only if safe!)
git push --force-with-lease origin feature/your-branch

# Or reset to remote
git reset --hard origin/feature/your-branch
```

### Common GitHub Problems

**PR Can't Be Merged**:
- Check for merge conflicts (resolve locally)
- Ensure CI checks pass
- Verify required reviews are approved
- Check branch protection rules

**Labels Not Showing**:
- Clear browser cache
- Check label spelling
- Verify label exists in repo

**Actions Not Running**:
- Check workflow file syntax (YAML validation)
- Verify triggers (`on:` section)
- Check repository Actions settings (enabled?)
- Review Actions logs for errors

---

## Quick Reference Cheatsheet

### Daily Workflow

```bash
# Start day
git checkout main && git pull

# Create feature branch
git checkout -b feature/my-feature

# Make changes, commit frequently
git add .
git commit -m "feat(scope): description"

# Push and create PR
git push -u origin feature/my-feature
gh pr create --title "..." --body "..."

# After PR merged
git checkout main && git pull
git branch -d feature/my-feature
```

### Common Commands

```bash
# Repository
gh repo view
gh repo edit --default-branch main

# Issues
gh issue create --title "..." --label "bug"
gh issue list --milestone "Phase 1"
gh issue close 123

# Pull Requests
gh pr create
gh pr list
gh pr review 123 --approve
gh pr merge 123 --squash

# Branches
git checkout -b feature/name
git branch -d feature/name
git push origin --delete feature/name
```

---

## Appendix: Templates & Scripts

### Automated Setup Script

```bash
#!/bin/bash
# File: setup-github-workflow.sh

echo "Setting up GitHub workflow infrastructure..."

# Create .github directory structure
mkdir -p .github/ISSUE_TEMPLATE
mkdir -p .github/workflows

# Create issue templates
cat > .github/ISSUE_TEMPLATE/bug_report.md << 'EOF'
---
name: Bug Report
about: Report a bug
title: '[BUG] '
labels: bug
---
[Template content here]
EOF

# Create PR template
cat > .github/pull_request_template.md << 'EOF'
## Summary
[Template content here]
EOF

# Create labels
labels=(
  "bug:d73a4a:Something isn't working"
  "enhancement:a2eeef:New feature or request"
  "documentation:0075ca:Documentation improvements"
)

for label_data in "${labels[@]}"; do
  IFS=':' read -r label color description <<< "$label_data"
  gh label create "$label" --color "$color" --description "$description" --force
done

# Configure branch protection
gh api repos/{owner}/{repo}/branches/main/protection -X PUT \
  -F required_pull_request_reviews='{"required_approving_review_count":1}' \
  -F enforce_admins=true

echo "✅ GitHub workflow setup complete!"
```

---

**End of Guide**

This guide provides a comprehensive, reusable framework for professional GitHub workflows. Adapt it to your specific project needs and team size.

For more information:
- [GitHub Docs](https://docs.github.com)
- [GitHub CLI Manual](https://cli.github.com/manual/)
- [Conventional Commits](https://www.conventionalcommits.org/)
- [Git Best Practices](https://git-scm.com/book/en/v2)
