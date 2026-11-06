from django.db import migrations, models


class Migration(migrations.Migration):
    """Reconcile the former REST-agent columns with the binary API model."""

    dependencies = [
        ("billing_api", "0026_tenant_mikrotik_api_mode"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    sql="""
                        ALTER TABLE billing_api_tenant
                        ADD COLUMN IF NOT EXISTS mikrotik_pass_encrypted text NOT NULL DEFAULT '';
                        UPDATE billing_api_tenant
                        SET mikrotik_pass_encrypted = ''
                        WHERE mikrotik_pass_encrypted IS NULL;
                        ALTER TABLE billing_api_tenant
                        ALTER COLUMN mikrotik_pass_encrypted SET DEFAULT '';
                        ALTER TABLE billing_api_tenant
                        ALTER COLUMN mikrotik_pass_encrypted SET NOT NULL;

                        ALTER TABLE billing_api_tenant
                        ADD COLUMN IF NOT EXISTS mikrotik_rest_port integer NOT NULL DEFAULT 443;
                        UPDATE billing_api_tenant
                        SET mikrotik_rest_port = 443
                        WHERE mikrotik_rest_port IS NULL;
                        ALTER TABLE billing_api_tenant
                        ALTER COLUMN mikrotik_rest_port SET DEFAULT 443;
                        ALTER TABLE billing_api_tenant
                        ALTER COLUMN mikrotik_rest_port SET NOT NULL;

                        ALTER TABLE billing_api_tenant
                        ADD COLUMN IF NOT EXISTS mikrotik_tls_fingerprint varchar(128) NOT NULL DEFAULT '';
                        UPDATE billing_api_tenant
                        SET mikrotik_tls_fingerprint = ''
                        WHERE mikrotik_tls_fingerprint IS NULL;
                        ALTER TABLE billing_api_tenant
                        ALTER COLUMN mikrotik_tls_fingerprint SET DEFAULT '';
                        ALTER TABLE billing_api_tenant
                        ALTER COLUMN mikrotik_tls_fingerprint SET NOT NULL;
                    """,
                    reverse_sql=migrations.RunSQL.noop,
                ),
            ],
            state_operations=[
                migrations.AddField(
                    model_name="tenant",
                    name="mikrotik_pass_encrypted",
                    field=models.TextField(blank=True, default=""),
                ),
                migrations.AddField(
                    model_name="tenant",
                    name="mikrotik_rest_port",
                    field=models.IntegerField(default=443),
                ),
                migrations.AddField(
                    model_name="tenant",
                    name="mikrotik_tls_fingerprint",
                    field=models.CharField(blank=True, default="", max_length=128),
                ),
            ],
        ),
    ]
