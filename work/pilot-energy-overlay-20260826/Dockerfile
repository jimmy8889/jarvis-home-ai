ARG BASE_IMAGE
FROM ${BASE_IMAGE}

USER root
COPY overlay/pilot_core/ /usr/local/lib/python3.13/site-packages/pilot_core/
COPY overlay/pilot_core/ /app/apps/pilot-core/pilot_core/
USER pilot
