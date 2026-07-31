CREATE TABLE `finding_checks` (
	`id` text PRIMARY KEY NOT NULL,
	`finding_id` text NOT NULL,
	`ordinal` integer NOT NULL,
	`check_name` text NOT NULL,
	`result_kind` text,
	`result_num` real,
	`status` text DEFAULT 'ok' NOT NULL,
	`reason` text,
	FOREIGN KEY (`finding_id`) REFERENCES `findings`(`id`) ON UPDATE cascade ON DELETE cascade,
	CONSTRAINT "finding_checks_status_enum" CHECK("finding_checks"."status" IN ('ok','skipped','errored')),
	CONSTRAINT "finding_checks_result_kind_enum" CHECK("finding_checks"."result_kind" IS NULL OR "finding_checks"."result_kind" IN ('bool','number')),
	CONSTRAINT "finding_checks_result_paired" CHECK(("finding_checks"."result_kind" IS NULL) = ("finding_checks"."result_num" IS NULL)),
	CONSTRAINT "finding_checks_bool_domain" CHECK("finding_checks"."result_kind" <> 'bool' OR "finding_checks"."result_num" IN (0, 1)),
	CONSTRAINT "finding_checks_status_consistent" CHECK(("finding_checks"."status" = 'ok' AND "finding_checks"."result_kind" IS NOT NULL) OR ("finding_checks"."status" <> 'ok' AND "finding_checks"."result_kind" IS NULL AND "finding_checks"."reason" IS NOT NULL))
);
--> statement-breakpoint
CREATE UNIQUE INDEX `finding_checks_finding_ordinal_key` ON `finding_checks` (`finding_id`,`ordinal`);--> statement-breakpoint
CREATE INDEX `finding_checks_name_idx` ON `finding_checks` (`check_name`);--> statement-breakpoint
CREATE TABLE `findings` (
	`id` text PRIMARY KEY NOT NULL,
	`run_id` text NOT NULL,
	`ordinal` integer NOT NULL,
	`finding_key` text NOT NULL,
	`target` text,
	`label` text,
	`anchor_quote` text,
	`anchor_page` integer,
	`span_start` integer,
	`span_end` integer,
	`verdict` text,
	`evidence` text NOT NULL,
	`note` text,
	FOREIGN KEY (`run_id`) REFERENCES `runs`(`id`) ON UPDATE cascade ON DELETE cascade,
	CONSTRAINT "findings_page_ge1" CHECK("findings"."anchor_page" IS NULL OR "findings"."anchor_page" >= 1),
	CONSTRAINT "findings_span_valid" CHECK(("findings"."span_start" IS NULL AND "findings"."span_end" IS NULL) OR ("findings"."span_start" >= 0 AND "findings"."span_end" >= "findings"."span_start")),
	CONSTRAINT "findings_anchor_shape" CHECK("findings"."anchor_quote" IS NOT NULL OR ("findings"."anchor_page" IS NULL AND "findings"."span_start" IS NULL AND "findings"."span_end" IS NULL)),
	CONSTRAINT "findings_verdict_enum" CHECK("findings"."verdict" IS NULL OR "findings"."verdict" IN ('supported','overstated','unsupported','contradicted','unverifiable'))
);
--> statement-breakpoint
CREATE UNIQUE INDEX `findings_run_ordinal_key` ON `findings` (`run_id`,`ordinal`);--> statement-breakpoint
CREATE INDEX `findings_run_key_idx` ON `findings` (`run_id`,`finding_key`);--> statement-breakpoint
CREATE TABLE `ledger_rows` (
	`id` text PRIMARY KEY NOT NULL,
	`run_id` text NOT NULL,
	`ordinal` integer NOT NULL,
	`check_name` text NOT NULL,
	`label` text,
	`detail` text,
	`result_kind` text,
	`result_num` real,
	`status` text DEFAULT 'ok' NOT NULL,
	`reason` text,
	FOREIGN KEY (`run_id`) REFERENCES `runs`(`id`) ON UPDATE cascade ON DELETE cascade,
	CONSTRAINT "ledger_rows_status_enum" CHECK("ledger_rows"."status" IN ('ok','skipped','errored')),
	CONSTRAINT "ledger_rows_result_kind_enum" CHECK("ledger_rows"."result_kind" IS NULL OR "ledger_rows"."result_kind" IN ('bool','number')),
	CONSTRAINT "ledger_rows_result_paired" CHECK(("ledger_rows"."result_kind" IS NULL) = ("ledger_rows"."result_num" IS NULL)),
	CONSTRAINT "ledger_rows_bool_domain" CHECK("ledger_rows"."result_kind" <> 'bool' OR "ledger_rows"."result_num" IN (0, 1)),
	CONSTRAINT "ledger_rows_status_consistent" CHECK(("ledger_rows"."status" = 'ok' AND "ledger_rows"."result_kind" IS NOT NULL) OR ("ledger_rows"."status" <> 'ok' AND "ledger_rows"."result_kind" IS NULL AND "ledger_rows"."reason" IS NOT NULL))
);
--> statement-breakpoint
CREATE UNIQUE INDEX `ledger_rows_run_ordinal_key` ON `ledger_rows` (`run_id`,`ordinal`);--> statement-breakpoint
CREATE INDEX `ledger_rows_check_kind_idx` ON `ledger_rows` (`check_name`,`result_kind`,`result_num`);--> statement-breakpoint
CREATE TABLE `runs` (
	`id` text PRIMARY KEY NOT NULL,
	`submission_id` text NOT NULL,
	`report_sha256` text NOT NULL,
	`schema_version` text NOT NULL,
	`solicitation` text,
	`run_date` text,
	`run_seconds` real,
	`run_version` text,
	`cost_usd` real,
	`recommendation` text NOT NULL,
	`created_at` integer NOT NULL,
	FOREIGN KEY (`submission_id`) REFERENCES `submissions`(`id`) ON UPDATE cascade ON DELETE cascade,
	CONSTRAINT "runs_cost_ge0" CHECK("runs"."cost_usd" IS NULL OR "runs"."cost_usd" >= 0)
);
--> statement-breakpoint
CREATE UNIQUE INDEX `runs_report_sha256_key` ON `runs` (`report_sha256`);--> statement-breakpoint
CREATE INDEX `runs_submission_created_idx` ON `runs` (`submission_id`,`created_at`);--> statement-breakpoint
CREATE TABLE `submissions` (
	`id` text PRIMARY KEY NOT NULL,
	`text_sha256` text NOT NULL,
	`text_length` integer NOT NULL,
	`file` text NOT NULL,
	`file_sha256` text,
	`pages` integer,
	`page_offsets` text,
	`media_type` text,
	`title` text,
	`byline` text,
	`submitter` text,
	`created_at` integer NOT NULL,
	CONSTRAINT "submissions_pages_ge0" CHECK("submissions"."pages" IS NULL OR "submissions"."pages" >= 0),
	CONSTRAINT "submissions_text_length_ge0" CHECK("submissions"."text_length" >= 0)
);
--> statement-breakpoint
CREATE UNIQUE INDEX `submissions_text_sha256_key` ON `submissions` (`text_sha256`);