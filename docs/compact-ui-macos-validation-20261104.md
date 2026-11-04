# Compact notebook and transcript UI — Mac validation

Installed release: **0.3.36 / build 46**. Scope: notebook toolbar, supporting notebook panels, and transcript reading space. No database migration, model change, or new dependency.

## Resulting behavior

- Idle pen, highlighter, eraser, text, selection and movement buttons have no persistent box outline. The selected tool keeps its existing fill and thin outline. Keyboard focus remains a separate visible ring; disabled tools remain disabled.
- The notebook supporting area has **메모 / 인식·검토 / 연결** tabs. Memo includes both session memo and current-page memo where available. Changing these tabs hides their contents without unmounting the editors or changing the active PDF page. Other screens retain their existing recognition/knowledge accordions.
- At narrow widths the supporting area continues below the PDF. It is not replaced with a modal drawer.
- The transcript uses a smaller title, compact idle recorder and inline utility disclosures. Long static instructions are below the text in **대본 사용 안내**. Recording, recovery, stop, interruption, missing-audio ranges, retry and error handling remain in their existing paths.

## Acceptance evidence

Real installed `Solasi.app`, not a browser substitute, was exercised at **680 × 480** in light and dark modes.

| Check | Observation |
| --- | --- |
| Toolbar layout | Tools, undo/redo, save and zoom remain available without overlapping. Idle outlines are removed and the selected tool remains distinct in both themes. |
| Tool settings | Selecting pen and clicking it again still opens its color/width/opacity settings. |
| Supporting tabs | Memo, recognition and connections display one pane at a time. Right arrow advances the pane; Home returns to Memo with visible keyboard focus. |
| Recognition draft | A temporary, unapproved text was entered in an existing QA candidate. After switching to Connections and back it remained unchanged. The input was restored to its original empty value; no approval or inference was invoked. |
| Session memo | A temporary unsaved memo survived switching to Recognition and back. The existing revert action restored the original input. The page memo remained separate and unchanged. |
| Transcript layout | The initial 680 × 480 view now shows the first transcript sentence. The before screenshot at the same size showed only the header, recorder and utilities. |
| Transcript actions | Sentence selection exposed listen/edit actions. Existing original audio played; editing and cancellation remained available. Optional instructions could be expanded below the text. No transcript edit was saved. |
| Original data | All **4,120 existing rows in 11 protected record/ink/draft/source tables** matched the pre-install snapshot. SHA256 matched for **62 original/audio files**. |
| Preferences | Original global tool, layout and theme preferences were restored. Window frame remained 680 × 480. |
| Package | Installed frontend matched the tested source build. Existing engine and native executable were reused; strict code signature verification passed. |

Automated validation: **131 frontend tests passed**, including new embedded-panel and transcript-help checks; TypeScript checking and production build passed. A separate reviewer found no actionable issue in the scoped change.

Private screenshots, accessibility snapshots, backup and preservation receipts are kept in `.local-state/compact-ui-20261104/`; they are excluded from Git. No user PDFs, recordings, screenshots or database snapshots are published with this change.

## Limits

No new long recording, model accuracy benchmark or OCR inference was run for this UI change. Existing audio and review candidates were used. On the 135-page PDF, the UI tool's accessibility snapshot truncated the children after 100 siblings, so panel checks used screenshots and a shorter existing QA document. Intermittent native capture failures recovered after refreshing the app binding; their internal tool cause remains unconfirmed.
