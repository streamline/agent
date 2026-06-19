# Nova Fly Overlay

This directory contains the Streamline Nova `/chat` bridge that is layered on top of the public `ghcr.io/streamline/agent:latest` base image for Fly.io.

## Build/deploy pattern

The production Nova app currently builds from `/opt/data/Dockerfile.nova`, which uses the same pattern:

```dockerfile
FROM ghcr.io/streamline/agent:latest
COPY nova-chat_server.py /opt/nova/chat_server.py
COPY nova-soul.md /opt/nova/soul.md
ENTRYPOINT ["/usr/bin/python3", "/opt/nova/chat_server.py"]
```

## Behavior gates

Run the eval suite before and after deployment:

```bash
python3 samantha_v2_eval.py --target local
python3 samantha_v2_eval.py --target https://nova-streamline.fly.dev
```

Core checks:

- HTML/landing-page requests return attached `.html` files, not raw HTML in Telegram.
- Payment/upgrade requests return a checkout/portal link directly.
- Settings/login requests return the `sammm.app/settings` Telegram-login flow.
- Vague business automation prompts ask one sharp question, not a brochure.
- Spanish input gets a Spanish reply.
