# Sandbox image for run_python. Built separately from the control plane:
#   docker build -t ai-platform-sandbox-python:1 code-sandbox-service/images/python
#
# Public-safe by construction: no secrets, no sensitive ENV. Runtime `pip install`
# is not supported (sandboxes have no network) — this fixed, pre-tested stack is the
# contract, and it is listed in the run_python MCP tool description. Change both together.
FROM python:3.12-slim

ARG PIP_INDEX_URL=https://package-mirror.liara.ir/repository/pypi/simple

RUN apt-get update && apt-get install -y --no-install-recommends \
        tini coreutils tar fonts-vazirmatn fontconfig \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir --index-url "$PIP_INDEX_URL" \
        pandas==2.2.3 \
        numpy==2.1.3 \
        matplotlib==3.9.4 \
        openpyxl==3.1.5 \
        python-docx==1.1.2 \
        pymupdf==1.25.1 \
        scipy==1.14.1 \
        scikit-learn==1.6.0 \
        tabulate==0.9.0

# Persian-capable default font for charts. A separate rc file selected via MATPLOTLIBRC: editing matplotlib's own
# matplotlibrc makes it print "Duplicate key" warnings into every script's stderr.
RUN printf 'font.family: sans-serif\nfont.sans-serif: Vazirmatn, DejaVu Sans\naxes.unicode_minus: False\n' > /etc/matplotlibrc \
    && fc-cache -f
ENV MATPLOTLIBRC=/etc/matplotlibrc

# Smoke test: every preinstalled library imports, and the font resolves.
RUN MPLBACKEND=Agg MPLCONFIGDIR=/tmp/mpl-build python -c "\
import pandas, numpy, scipy, sklearn, openpyxl, docx, fitz, tabulate, matplotlib; \
from matplotlib import font_manager as fm; \
p = fm.findfont('Vazirmatn', fallback_to_default=False); print('font:', p)" \
    && rm -rf /tmp/mpl-build

RUN groupadd --gid 1000 sandbox \
    && useradd --uid 1000 --gid 1000 --no-create-home --home-dir /workspace --shell /usr/sbin/nologin sandbox

LABEL ai-platform.sandbox.image="python-3.12-1"
WORKDIR /workspace
USER 1000:1000
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["sleep", "infinity"]
