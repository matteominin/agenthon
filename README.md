# agenthon

## Open WebUI demo

Employees use the TDB model in Open WebUI. The separate Gradio dashboard shows request history, risk and trace events from the same proxy.

1. Export `DEEPSEEK_API_KEY` and optionally `DEEPSEEK_MODEL` in the proxy environment. From this checkout, start both the dashboard and the local transport:
   ```sh
   PYTHONPATH=src uv run --no-project --with gradio==6.32.0 --with markdown-it-py --with jsonschema --with 'spacy>=3.8,<3.9' --with 'https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl' -- python -m agenthon.ui.app
   ```
2. In Open WebUI, open **Admin Panel → Functions**, create a function with ID `tdb`, paste the contents of `src/agenthon/ui/openwebui_pipe.py`, save and enable it. In the model access settings, grant the intended employees read access to the TDB model. Both services in this demo share a host network namespace. The Pipe connects server-side to `http://127.0.0.1:8765`. If deployed separately, provide a private network path and configure `TDB_PROXY_URL` on the Open WebUI server.
3. Select **TDB** in a new chat. Try a synthetic request from `data/demo/requests.json`. The review summary shows the original values in the employee’s chat. Click a placeholder in the Markdown preview to send its original value on approval, and click again to keep it masked. The simulated local route uses the masked proposal. You can approve the masked text, edit and recheck, or select the simulated route. **Check edited prompt** updates the review in the same assistant message and retains placeholders that still appear in the draft. **Send redacted version** replaces that review with the answer. If the tab was reloaded before approval, resubmit the original request to open a fresh review.
4. Open the dashboard at `http://127.0.0.1:7860`. Select a row to inspect the original and sent prompts, response and trace. The demo keeps request history in memory. Set `TDB_ADMIN_HOST` and `TDB_ADMIN_PORT` to change the admin listener.
