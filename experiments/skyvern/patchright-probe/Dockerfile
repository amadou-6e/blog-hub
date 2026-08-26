FROM public.ecr.aws/skyvern/skyvern@sha256:18defe240c49c79c749c57f7e9008b1a169aa34193b267002c7e5ee437e28887

COPY patchright-requirements.txt /tmp/patchright-requirements.txt
RUN pip install --no-cache-dir --no-deps --require-hashes \
      -r /tmp/patchright-requirements.txt \
    && rm /tmp/patchright-requirements.txt \
    && test -x /root/.cache/ms-playwright/chromium-1134/chrome-linux/chrome

COPY patchright-probe/probe.py /experiment/probe.py

ENTRYPOINT ["xvfb-run", "-a", "python", "/experiment/probe.py"]
