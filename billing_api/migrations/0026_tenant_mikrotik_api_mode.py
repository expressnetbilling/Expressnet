from django.db import migrations, models


class Migration(migrations.Migration):
    """Reconcile the legacy Railway column with the Django Tenant model.

    Some deployed databases received this NOT NULL column outside the tracked
    migration history.  New Tenant inserts then omitted it and registration
    failed.  The conditional SQL supports both those installations and clean
    databases created solely from this repository's migration history.
    """

    dependencies = [("billing_api", "0025_payment_provider_callback_indexes")]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    sql="""
                        DO $$
                        BEGIN
                            IF EXISTS (
                                SELECT 1
                                FROM information_schema.columns
                                WHERE table_schema = current_schema()
                                  AND table_name = 'billing_api_tenant'
                                  AND column_name = 'mikrotik_api_mode'
                            ) THEN
                                UPDATE billing_api_tenant
                                SET mikrotik_api_mode = 'auto'
                                WHERE mikrotik_api_mode IS NULL OR mikrotik_api_mode = '';
                                ALTER TABLE billing_api_tenant
                                ALTER COLUMN mikrotik_api_mode SET DEFAULT 'auto';
                                ALTER TABLE billing_api_tenant
                                ALTER COLUMN mikrotik_api_mode SET NOT NULL;
                            ELSE
                                ALTER TABLE billing_api_tenant
                                ADD COLUMN mikrotik_api_mode varchar(20) NOT NULL DEFAULT 'auto';
                            END IF;
                        END $$;
                    """,
                    reverse_sql=migrations.RunSQL.noop,
                ),
            ],
            state_operations=[
                migrations.AddField(
                    model_name="tenant",
                    name="mikrotik_api_mode",
                    field=models.CharField(blank=True, default="auto", max_length=20),
                ),
            ],
        ),
    ]
