# Sources and design basis

Official references checked on 31 October 2026. The selected baseline must be reviewed again when dependencies are locked. External sources guide design; they do not validate the resulting implementation.

## S01 Course provided Flask Project Rubric

Flask_Project_Rubric(1).pdf

Pages 2 to 4; course CSE601330; 100 marks; minimum 40 related SQLAlchemy tables.

## S02 Flask installation

https://flask.palletsprojects.com/en/stable/installation/

Virtual environments and supported Python versions.

## S03 Flask security considerations

https://flask.palletsprojects.com/en/stable/web-security/

CSRF cookies headers host validation and bounded requests.

## S04 Flask production deployment

https://flask.palletsprojects.com/en/stable/deploying/

Dedicated production WSGI server and proxy configuration.

## S05 Flask SQLAlchemy quick start

https://flask-sqlalchemy.palletsprojects.com/en/stable/quickstart/

SQLAlchemy 2 style model and session usage.

## S06 PostgreSQL versioning policy

https://www.postgresql.org/support/versioning/

Use current maintenance release of a supported major.

## S07 SQLAlchemy transactions

https://docs.sqlalchemy.org/en/20/orm/session_transaction.html

Explicit transaction boundaries and rollback.

## S08 OWASP ASVS

https://asvs.owasp.org/

Applicable security requirements and verification evidence.

## S09 GS1 retail traceability guideline

https://ref.gs1.org/guidelines/2d-in-retail/

Batch and serial identifiers support targeted recall workflows.

## S10 Flask Limiter storage configuration

https://flask-limiter.readthedocs.io/en/stable/configuration.html

Shared persistent counters instead of process local rate limits.

## S11 Flask Session security

https://flask-session.readthedocs.io/en/latest/security.html

Server session identifier regeneration.

## S12 Celery Redis broker

https://docs.celeryq.dev/en/stable/getting-started/backends-and-brokers/redis.html

Worker delivery retry and Redis broker configuration.

## S13 PostgreSQL recursive queries

https://www.postgresql.org/docs/17/queries-with.html

Recursive traversal and cycle handling.

## S14 OWASP password storage

https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html

Argon2id password hashing guidance.
