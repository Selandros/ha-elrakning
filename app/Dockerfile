ARG BUILD_FROM
FROM ${BUILD_FROM}

WORKDIR /app
COPY app/elrakning_app /app/elrakning_app
COPY custom_components/elrakning/app_contract.py /app/elrakning_app/app_contract.py
COPY app/run.sh /run.sh
RUN chmod 0755 /run.sh

CMD ["/run.sh"]
