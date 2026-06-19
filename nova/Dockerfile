FROM ghcr.io/streamline/agent:latest

RUN mkdir -p /opt/nova
COPY nova/chat_server.py /opt/nova/chat_server.py

ENV CHAT_SERVER_HOST=0.0.0.0
ENV CHAT_SERVER_PORT=8443
EXPOSE 8443
ENTRYPOINT ["/usr/bin/python3", "/opt/nova/chat_server.py"]
