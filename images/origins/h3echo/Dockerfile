FROM http-prism-soil:latest

RUN "$VIRTUAL_ENV/bin/pip" install aioquic

COPY h3echo.py /app/h3echo.py

CMD ["/app/venv/bin/python", "/app/h3echo.py", \
     "--host", "::", \
     "--port", "443", \
     "--certificate", "/app/prism.crt", \
     "--private-key", "/app/prism.crt.key"]
