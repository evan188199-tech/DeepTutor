# Findings — builtin tool specs / registry / implementation parity

**No ERROR-level drift found between specs, registry consumption and implementations.**

## [WARN] Orphan BaseTool subclass not declared in the catalog

class EditFileTool (name='edit_file') inherits BaseTool but has no BUILTIN_TOOL_SPECS entry; its module is imported nowhere in deeptutor/ runtime code (tests only), so the registry can never serve it

- evidence: `deeptutor/tools/file_tools.py:134`
- fix: declare it in builtin_specs.py or remove the dead implementation (+ its test)

## [WARN] Orphan BaseTool subclass not declared in the catalog

class ListDirTool (name='list_dir') inherits BaseTool but has no BUILTIN_TOOL_SPECS entry; its module is imported nowhere in deeptutor/ runtime code (tests only), so the registry can never serve it

- evidence: `deeptutor/tools/file_tools.py:189`
- fix: declare it in builtin_specs.py or remove the dead implementation (+ its test)

## [WARN] Orphan BaseTool subclass not declared in the catalog

class ReadFileTool (name='read_file') inherits BaseTool but has no BUILTIN_TOOL_SPECS entry; its module is imported nowhere in deeptutor/ runtime code (tests only), so the registry can never serve it

- evidence: `deeptutor/tools/file_tools.py:41`
- fix: declare it in builtin_specs.py or remove the dead implementation (+ its test)

## [WARN] Orphan BaseTool subclass not declared in the catalog

class WriteFileTool (name='write_file') inherits BaseTool but has no BUILTIN_TOOL_SPECS entry; its module is imported nowhere in deeptutor/ runtime code (tests only), so the registry can never serve it

- evidence: `deeptutor/tools/file_tools.py:109`
- fix: declare it in builtin_specs.py or remove the dead implementation (+ its test)

## [WARN] AGENTS.md toggle table missing a user-toggleable tool

USER_TOGGLEABLE_TOOL_NAMES lists 'zotero_search' but the AGENTS.md Level 1 table omits it

- evidence: `deeptutor/tools/builtin/__init__.py:1984`
- evidence: `AGENTS.md:41`
- fix: update the doc table (or the tuple if the doc is right)

## [INFO] Spec class_path points at a re-export

deeptutor.capabilities.reading.tools:ViewFigureTool is imported into deeptutor/capabilities/reading/tools.py but defined in deeptutor/capabilities/reading/figure_view.py; import resolution works, but the catalog indirection is one hop deeper than it looks

- evidence: `deeptutor/tools/builtin_specs.py:186`
- evidence: `deeptutor/capabilities/reading/figure_view.py:1`
- fix: consider pointing the spec at the defining module

## [INFO] PARTNER_BUILTIN_TOOL_NAMES duplicated but currently in sync

two hand-maintained copies match today; a future edit on one side would silently diverge

- evidence: `deeptutor/tools/builtin_specs.py:224`
- evidence: `deeptutor/tools/partner_memory.py:26`
- fix: single-source the tuple (one module defines it, the other imports)

