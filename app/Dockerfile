ARG BUILD_FROM
FROM ${BUILD_FROM}

WORKDIR /app
COPY elrakning_app /app/elrakning_app
COPY run.sh /run.sh
RUN chmod 0755 /run.sh

CMD ["/run.sh"]
