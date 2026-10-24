"""The app that hosts the agent: ADK's own, with the activator in its lifespan."""

import importlib


def test_the_activator_is_attached_to_adks_app(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "fake/model")
    monkeypatch.setenv("COMPONENT_NAME", "BookingAgent")  # the Dockerfile sets it
    app_module = importlib.import_module("booking_agent.app")

    assert app_module.app.router.lifespan_context.__qualname__.startswith("attach.")
    assert app_module.agent.name == "booking_agent"
    assert [route.path for route in app_module.app.routes if route.path == "/run"]  # ADK's host
