# Guidelines for Successful File Edits

When using an edit tool that requires an `old_string` to match existing file content before replacing it with a `new_string`, precision is critical. Follow these general steps to maximize the likelihood of a successful edit and avoid "String to replace not found" errors:

1.  **Refresh File Content**: Always read the target file immediately before attempting an edit. This ensures you are working with the absolute latest version of the file, minimizing discrepancies caused by prior (potentially unseen or forgotten) modifications.

2.  **Exact `old_string` Construction**:
    *   Carefully copy the segment of text you intend to replace (`old_string`) directly from the fresh output of your file read operation.
    *   **Crucial**: Ensure that any metadata added by the read tool (e.g., line numbers, leading tabs for formatting the read output) is *excluded* from the `old_string`. The `old_string` must only contain the actual characters present in the file itself.
    *   Pay meticulous attention to all whitespace, including spaces, tabs, and newline characters. These must exactly match the file content.
    *   Hidden or non-rendering characters can also cause mismatches. Be wary if copying from sources that might introduce them.

3.  **Context Management for `old_string`**:
    *   Start by defining `old_string` with a moderate amount of context: the specific line(s) to be changed, plus at least one line immediately before and one line immediately after. This helps ensure uniqueness without being overly verbose.
    *   If an edit fails, and you are certain about the content of the lines to be changed, incrementally increase the context (more lines before and after) for `old_string`. This can help overcome ambiguities if the shorter segment appears multiple times in the file.
    *   Conversely, if a larger block fails, try reducing context to pinpoint the exact line or character causing the mismatch, ensuring the smaller segment is genuinely unique at the intended edit location.

4.  **`new_string` Construction**: Construct the `new_string` with the same attention to detail as `old_string`, ensuring it accurately represents the desired state of the code, including correct indentation and whitespace.

5.  **Iterative Refinement**: If an edit fails, do not assume the tool is faulty. Systematically re-verify steps 1-4. Common culprits are:
    *   Slight differences in indentation (tabs vs. spaces, or number of spaces).
    *   Variations in newline characters (CRLF vs. LF) if not handled consistently.
    *   Using stale file content to construct `old_string`.
    *   Including read-tool artifacts (like line numbers) in `old_string`.

6.  **Strategies for Complex or Failing Multi-line Edits**:
    *   **Verify with Single-Line Edits**: If a multi-line `Edit` repeatedly fails despite careful `old_string` construction, attempt to modify a *single, simple line* within the target block with minimal context. Success here confirms basic editability and points to subtle issues in the larger `old_string`. The file content *after* this small successful edit becomes the new baseline for subsequent `old_string` constructions.
    *   **Use `MultiEdit` for Staged Changes**: For complex transformations or when direct `Edit` of a large block is problematic, consider using the `MultiEdit` tool. Break down the overall change into a sequence of smaller, atomic edits. Each step in `MultiEdit` operates on the result of the previous one. This can be more robust for intricate modifications or when dealing with code that has many special characters or complex indentation. Ensure each `old_string` in the sequence precisely matches the expected state of the code after the preceding edit in the `MultiEdit` chain.

By adhering to these principles, particularly the exclusion of read-tool artifacts and the exact replication of file content and whitespace, the reliability of string replacement edits can be significantly improved.

# Commit Messages

When generating commit messages, do not include the `Co-Authored-By: Claude <noreply@anthropic.com>` line or the `🤖 Generated with [Claude Code](https://claude.ai/code)` line.

# Interaction Note

When providing code modifications or suggesting edits, directly apply these changes using the available tools rather than asking the user to manually implement them. If a change is proposed, it will be accompanied by the tool usage that performs the edit. This ensures a more efficient workflow.
