-- Run once as TeslaMate's database owner. Replace the two psql variables.
-- psql -v pilot_role=pilot_teslamate_reader -v pilot_password='generated secret' -f create-readonly-role.sql
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'pilot_role', :'pilot_password')
 WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'pilot_role') \gexec
ALTER ROLE :"pilot_role" SET default_transaction_read_only = on;
ALTER ROLE :"pilot_role" SET statement_timeout = '5s';
ALTER ROLE :"pilot_role" SET lock_timeout = '1s';
GRANT CONNECT ON DATABASE teslamate TO :"pilot_role";
GRANT USAGE ON SCHEMA public TO :"pilot_role";
GRANT SELECT ON cars, drives, positions, addresses, geofences,
                charging_processes, charges TO :"pilot_role";
REVOKE CREATE ON SCHEMA public FROM :"pilot_role";
REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER
    ON ALL TABLES IN SCHEMA public FROM :"pilot_role";
