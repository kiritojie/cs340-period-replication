# GitHub Desktop: Manual Integration

This cleanup did not Commit, Push, Fetch, merge or modify the Git index.
The current submission count is in [SUBMISSION.md](SUBMISSION.md).

1. In GitHub Desktop, inspect Changes against [submission-files.csv](submission-files.csv).
   The ignored historical originals remain on disk and are already preserved in
   the two reviewed evidence packages. Final tables/plots and the three FREEZE
   descriptors remain visible.
2. Keep the current work on a dedicated local branch if possible. Review README,
   .gitattributes and .gitignore, then make the local commit yourself.
3. Fetch current origin/main. The previously checked live main was 5d1fd043;
   cached origin/main 47c71e5 is stale and neither value guarantees today's head.
4. Merge current main into the contribution branch. Preserve teammates' CPU
   Affinity Extension, Table 2 comparison and contributor credits, plus this
   cohort's navigation and results. Resolve .gitattributes by retaining both
   remote script LF rules and local evidence/vendor byte-preserving rules.
   Resolve any .gitignore overlap by retaining existing protections and the
   narrow two-archive exceptions. Do not replace whole files with one side.
5. Review the final Changes/history, then use normal Push and a Pull Request to
   main. If the group instead submits directly to main, first complete the same
   ordinary merge/review process; do not overwrite newer remote work.

If a merge reports conflicts, resolve them before continuing. Do not use Force
Push, reset --hard or discard changes. The 11 teammate links absent from this
local checkout are preserved and resolve after their remote files are integrated.
This cleanup's SHA audit protects 504 currently tracked teammate data files;
it does not claim that a Git merge has already happened.

Suggested commit subject:
~~~text
Finalize Table 2 RQ1 results and streamline evidence navigation
~~~

For command-line staging only, the reviewed allowlist remains staging-paths.txt.
It is optional; GitHub Desktop can stage the same Changes manually.
