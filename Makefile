RSYNC_SYNC = rsync -a --delete --exclude='.venv' --exclude='__pycache__' --exclude='.pytest_cache' --exclude='*.pyc'
RSYNC_CHECK = rsync -ani --delete --exclude='.venv' --exclude='__pycache__' --exclude='.pytest_cache' --exclude='*.pyc'

.PHONY: sync-plugin verify-plugin

sync-plugin:
	$(RSYNC_SYNC) mcp_server/ plugin/mcp_server/
	$(RSYNC_SYNC) skills/ plugin/skills/
	$(RSYNC_SYNC) assets/ plugin/assets/
	$(RSYNC_SYNC) .codex-plugin/ plugin/.codex-plugin/
	cp .mcp.json plugin/.mcp.json
	cp README.md plugin/README.md

verify-plugin:
	@out="$$( $(RSYNC_CHECK) mcp_server/ plugin/mcp_server/ )"; test -z "$$out" || { printf '%s\n' "$$out"; exit 1; }
	@out="$$( $(RSYNC_CHECK) skills/ plugin/skills/ )"; test -z "$$out" || { printf '%s\n' "$$out"; exit 1; }
	@out="$$( $(RSYNC_CHECK) assets/ plugin/assets/ )"; test -z "$$out" || { printf '%s\n' "$$out"; exit 1; }
	@out="$$( $(RSYNC_CHECK) .codex-plugin/ plugin/.codex-plugin/ )"; test -z "$$out" || { printf '%s\n' "$$out"; exit 1; }
	@cmp -s .mcp.json plugin/.mcp.json || { echo ".mcp.json drifted"; exit 1; }
	@cmp -s README.md plugin/README.md || { echo "README.md drifted"; exit 1; }
