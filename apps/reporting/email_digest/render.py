from __future__ import annotations

from jinja2 import Environment, FileSystemLoader

from apps.reporting.email_digest.contracts import ExecutiveDigestPayload


def render_executive_digest_html(payload: ExecutiveDigestPayload) -> str:
    env = Environment(loader=FileSystemLoader("templates"))
    template = env.get_template("executive_digest.html")
    return template.render(payload=payload)
