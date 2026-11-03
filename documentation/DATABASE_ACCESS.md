# Database access before production

Use a dedicated application database/project. This tool provisions **database-level object access**, while Flask still enforces company/action permissions. It does not implement PostgreSQL tenant RLS or certify provider security. It preserves the 72 Core tables and creates no database, role, password or application record.

`operations/database_access.py` is operator-host tooling; it is not copied into the web image. Run commands from the checkout root with the reviewed Python dependencies. The PostgreSQL server must be version 17 or newer. Apply current migrations first as the migration owner, then provision access, and recheck after every migration or grant change.

## Prepare separate roles

The existing migration role must own all 72 Core tables, `alembic_version` and the three RecallTrace trigger functions. The runtime must be an existing, separate login with no role memberships, no ownership of the database/application objects, and these properties:

```sql
CREATE ROLE recalltrace_runtime LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
  NOREPLICATION NOBYPASSRLS NOINHERIT;
```

Run this only in an authenticated administrative session for the intended project. Set the password using the provider's secure mechanism or interactive psql `\password recalltrace_runtime`; never pass it as a shell argument or commit it. This tool does not create or change passwords. It refuses elevated or role-member runtimes rather than rewriting unrelated role settings.

Securely inject `DATABASE_ACCESS_ADMIN_URL` into the operator process, using the migration owner or another administrator authorized to manage these roles, ACLs and defaults. Use the `postgresql+psycopg://` scheme. Remote connections require `sslmode=verify-full` and an installed CA file selected by `sslrootcert`. Do not paste the URL into chat or expose it in command arguments. The tool does not source `.env`; it does not fall back to the application's runtime `DATABASE_URL`.

## Review and apply

```sh
.venv/bin/python -m operations.database_access check \
  --runtime-role recalltrace_runtime --migration-role YOUR_MIGRATION_ROLE

.venv/bin/python -m operations.database_access apply \
  --runtime-role recalltrace_runtime --migration-role YOUR_MIGRATION_ROLE \
  --dedicated-database
```

`check` runs a read-only catalog transaction and returns a redacted JSON result with findings and a failing exit code when access is unsafe. `apply` requires the explicit dedicated-database acknowledgement, performs all changes in one transaction, verifies the result and rolls everything back if verification fails. It does not truncate, seed, alter business rows or change migration metadata.

The acknowledgement covers these effects; do not use the tool on a shared application database without a separate policy review:

- Revoke database `CREATE`/`TEMPORARY` and public-schema `CREATE` from `PUBLIC`, existing `anon`/`authenticated`/`service_role` API roles, and the runtime. Existing `PUBLIC CONNECT` is preserved; runtime receives explicit `CONNECT` and public-schema `USAGE`.
- Revoke direct table, column and trigger-function privileges from those public/API principals. Only the exact Core tables, Alembic table and three RecallTrace functions are modified; unrelated/provider tables are not changed.
- Remove table/sequence/function default grants to those principals and the runtime for the named migration owner, both globally and in `public`. Global function default revocation is necessary because PostgreSQL otherwise grants `PUBLIC EXECUTE`; it affects future functions created by that owner in other schemas too. New application objects receive no automatic runtime grant: review and reprovision deliberately.
- Grant runtime `SELECT/INSERT/UPDATE/DELETE` on ordinary Core tables, `SELECT/INSERT` on ten immutable history tables, and only `SELECT` on Alembic metadata. Grant no `TRUNCATE`, `REFERENCES`, `TRIGGER`, `MAINTAIN` or grant options. No sequence access is needed by the current UUID-based models.
- Set this role's connection search path to `pg_catalog, public`. Reject remaining schema-creation, temporary-table or trigger-disabling capabilities and inherited roles, so application trigger queries cannot be redirected through a writable schema.

Three immutable tables (`stock_transactions`, `trace_runs`, `case_comments`) also need **column-only `UPDATE(id)`** because PostgreSQL requires update privilege on at least one column for the existing `SELECT ... FOR UPDATE` workflows. They do not receive table-wide `UPDATE`. The migration's unconditional `BEFORE UPDATE OR DELETE` history trigger still rejects even `SET id = id`. Verification requires the reviewed guard body, migration ownership, `SECURITY INVOKER`, and an enabled, unconditional matching trigger on all ten immutable tables. Runtime cannot disable those triggers. Tests exercise actual runtime row locks and rejected mutation.

## Supabase and remaining checks

Do not rely on application permissions to protect a separate Supabase Data API. Use a dedicated project and disable the unused Data API or remove application schemas from its exposure in provider settings. Direct `anon`/`authenticated`/`service_role` access is revoked by this tool, including column grants. Unexpected public views/materialized views or `SECURITY DEFINER` routines make provisioning fail for explicit review: they can expose data indirectly even after table ACLs are removed. The tool does not delete or change them, inspect provider-exposed schema settings, or review other exposed schemas/provider extensions. Custom role memberships, RLS policies and alternate ownership require their own review.

Switch web and worker `DATABASE_URL` to the runtime login after provisioning. Keep migration/administrative credentials outside both services. Reconnect so the role's search path takes effect. Then run the real deployed acceptance checks: owner bootstrap/MFA, access isolation, stock posting/reversal, trace/recall workflows, background mail, private storage/scanning and recovery. A verified ACL report does not establish that these external services work.

The isolated PostgreSQL regression cases create fresh random databases/roles, migrate from scratch, exercise real runtime bootstrap/writes and forbidden operations, then remove their temporary resources. They never change grants on the development database or `recalltrace_test`:

```sh
.venv/bin/python -m pytest -q tests/test_database_access.py --tb=short
```
