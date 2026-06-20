CREATE VIEW IF NOT EXISTS mart_decision AS
SELECT
    d.seq,
    d.scenario_id,
    d.rec_id,
    d.policy,
    d.action,
    d.status,
    d.approver,
    d.decided_at,
    d.notes,
    d.data_fingerprint,
    d.engine_version,
    d.config_fingerprint,
    d.calibration_fingerprint,
    d.effective_calibration_fingerprint,
    json_extract(d.constraints_json, '$.roas_floor')            AS roas_floor,
    json_extract(d.constraints_json, '$.nc_cpa_target')         AS nc_cpa_target,
    json_extract(d.constraints_json, '$.prospecting_min_share') AS prospecting_min_share,
    json_extract(d.constraints_json, '$.movement_bound')        AS movement_bound,
    json_extract(d.constraints_json, '$.reserve_mode')          AS reserve_mode,
    (SELECT COUNT(*) FROM json_each(d.constraints_json, '$.calibration_overrides'))
        AS n_calibration_overrides,
    CASE WHEN (SELECT COUNT(*) FROM json_each(d.constraints_json, '$.calibration_overrides')) > 0
         THEN 1 ELSE 0 END                                      AS is_sensitivity_override,
    json_extract(d.binding_json, '$.solver.success')            AS solver_success,
    json_extract(d.binding_json, '$.solver.status')             AS solver_status,
    json_extract(d.binding_json, '$.solver.iterations')         AS solver_iterations,
    json_extract(d.binding_json, '$.solver.message')            AS solver_message,
    (SELECT COUNT(*) FROM json_each(d.allocation_json))         AS n_campaigns,
    (SELECT COALESCE(SUM(value), 0) FROM json_each(d.allocation_json))
        AS total_recommended_spend,
    (SELECT COUNT(*) FROM json_each(d.binding_json, '$.portfolio')
        WHERE json_extract(value, '$.status') = 'binding')      AS n_binding_constraints,
    (SELECT COUNT(*) FROM json_each(d.binding_json, '$.portfolio')
        WHERE json_extract(value, '$.status') = 'violated')     AS n_violated_constraints,
    (SELECT COUNT(*) FROM json_each(d.binding_json, '$.portfolio')
        WHERE json_extract(value, '$.status') = 'slack')        AS n_slack_constraints,
    (SELECT COUNT(*) FROM json_each(d.binding_json, '$.per_campaign'))
        AS n_campaign_bounds
FROM decisions d;
CREATE VIEW IF NOT EXISTS mart_decision_line AS
SELECT
    d.seq,
    d.scenario_id,
    d.decided_at,
    d.status,
    d.policy,
    a.key                                                       AS campaign_id,
    a.value                                                     AS recommended_spend,
    a.value / NULLIF((SELECT SUM(value) FROM json_each(d.allocation_json)), 0)
        AS spend_share
FROM decisions d, json_each(d.allocation_json) a;
CREATE VIEW IF NOT EXISTS mart_binding_constraint AS
SELECT
    d.seq,
    d.scenario_id,
    d.decided_at,
    d.status                                                    AS decision_status,
    json_extract(p.value, '$.name')                            AS constraint_name,
    json_extract(p.value, '$.status')                          AS constraint_status,
    json_extract(p.value, '$.detail')                          AS detail
FROM decisions d, json_each(d.binding_json, '$.portfolio') p;
CREATE VIEW IF NOT EXISTS mart_audit_chain AS
SELECT
    d.seq,
    d.scenario_id,
    d.decided_at,
    d.action,
    d.status,
    d.prev_hash,
    d.row_hash,
    d.data_fingerprint,
    d.engine_version,
    d.config_fingerprint,
    d.calibration_fingerprint,
    d.effective_calibration_fingerprint
FROM decisions d
ORDER BY d.seq;
