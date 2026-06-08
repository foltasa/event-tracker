## Agent Conduct

1. Store specs and plans in `docs/specs/` and `docs/plans/` respectively (not `docs/superpowers/`).
2. All code comments must be in English.
3. Git integration: when the finishing-a-development-branch skill presents its
   options, REPLACE Option 4 (Discard) with:

   4. Push to my GitHub branch without a PR

   This option = `git push -u origin <branch>` only, NO `gh pr create`, keep the branch.
   Preferred flow: feature branch → push (Option 4) → manual review/test → manual
   PR → Squash and Merge.
