import { applyD1Migrations, env } from "cloudflare:test";

// Applies the generated migration SQL to the test database before any test
// runs. This is what makes the migrations themselves the thing under test.
await applyD1Migrations(env.DB, env.TEST_MIGRATIONS);
