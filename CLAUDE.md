# Claude Code: Best Practices for Effective Collaboration

This document outlines best practices for working with Claude Code to ensure efficient and successful software development tasks.

## Task Management

For complex or multi-step tasks, Claude Code will use:
*   **TodoWrite**: To create a structured task list, breaking down the work into manageable steps. This provides clarity on the plan and allows for tracking progress.
*   **TodoRead**: To review the current list of tasks and their status, ensuring alignment and that all objectives are being addressed.

## File Handling and Reading

Understanding file content is crucial before making modifications.

1.  **Targeted Information Retrieval**:
    *   When searching for specific content, patterns, or definitions within a codebase, prefer using search tools like `Grep` or `Task` (with a focused search prompt). This is more efficient than reading entire files.

2.  **Reading File Content**:
    *   **Small to Medium Files**: For files where full context is needed or that are not excessively large, the `Read` tool can be used to retrieve the entire content.
    *   **Large File Strategy**:
        1.  **Assess Size**: Before reading a potentially large file, its size should be determined (e.g., using `ls -l` via the `Bash` tool or by an initial `Read` with a small `limit` to observe if content is truncated).
        2.  **Chunked Reading**: If a file is large (e.g., over a few thousand lines), it should be read in manageable chunks (e.g., 1000-2000 lines at a time) using the `offset` and `limit` parameters of the `Read` tool. This ensures all content can be processed without issues.
    *   Always ensure that the file path provided to `Read` is absolute.

## File Editing

Precision is key for successful file edits. The following strategies lead to reliable modifications:

1.  **Pre-Edit Read**: **Always** use the `Read` tool to fetch the content of the file *immediately before* attempting any `Edit` or `MultiEdit` operation. This ensures modifications are based on the absolute latest version of the file.

2.  **Constructing `old_string` (The text to be replaced)**:
    *   **Exact Match**: The `old_string` must be an *exact* character-for-character match of the segment in the file you intend to replace. This includes all whitespace (spaces, tabs, newlines) and special characters.
    *   **No Read Artifacts**: Crucially, do *not* include any formatting artifacts from the `Read` tool's output (e.g., `cat -n` style line numbers or display-only leading tabs) in the `old_string`. It must only contain the literal characters as they exist in the raw file.
    *   **Sufficient Context & Uniqueness**: Provide enough context (surrounding lines) in `old_string` to make it uniquely identifiable at the intended edit location. The "Anchor on a Known Good Line" strategy is preferred: `old_string` is a larger, unique block of text surrounding the change or insertion point. This is highly reliable.

3.  **Constructing `new_string` (The replacement text)**:
    *   **Exact Representation**: The `new_string` must accurately represent the desired state of the code, including correct indentation, whitespace, and newlines.
    *   **No Read Artifacts**: As with `old_string`, ensure `new_string` does *not* contain any `Read` tool output artifacts.

4.  **Choosing the Right Editing Tool**:
    *   **`Edit` Tool**: Suitable for a single, well-defined replacement in a file.
    *   **`MultiEdit` Tool**: Preferred when multiple changes are needed within the same file. Edits are applied sequentially, with each subsequent edit operating on the result of the previous one. This tool is highly effective for complex modifications.

5.  **Verification**:
    *   The success confirmation from the `Edit` or `MultiEdit` tool (especially if `expected_replacements` is used and matches) is the primary indicator that the change was made.
    *   If further visual confirmation is needed, use the `Read` tool with `offset` and `limit` parameters to view only the specific section of the file that was changed, rather than re-reading the entire file.

## Commit Messages

When Claude Code generates commit messages on your behalf:
*   The `Co-Authored-By: Claude <noreply@anthropic.com>` line will **not** be included.
*   The `🤖 Generated with [Claude Code](https://claude.ai/code)` line will **not** be included.

## General Interaction

Claude Code will directly apply proposed changes and modifications using the available tools, rather than describing them and asking you to implement them manually. This ensures a more efficient and direct workflow.