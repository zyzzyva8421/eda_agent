"""Root Cause Inference Engine – Phase A.

Public surface::

    from eda_agent.agent.inference.engine import infer, confirm

``infer(run_id)``  → ranked hypotheses + evidence + experiment suggestions
``confirm(inference_id, cause_id)``  → write confirmed cause back to DB + case_memory
"""
