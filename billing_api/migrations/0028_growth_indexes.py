from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("billing_api", "0027_tenant_mikrotik_pass_encrypted_compatibility"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="tenant",
            index=models.Index(fields=["status", "created_at"], name="tenant_status_created_idx"),
        ),
        migrations.AddIndex(
            model_name="voucher",
            index=models.Index(fields=["tenant", "status", "created_at"], name="voucher_tenant_state_idx"),
        ),
        migrations.AddIndex(
            model_name="voucher",
            index=models.Index(fields=["tenant", "service_type"], name="voucher_tenant_service_idx"),
        ),
        migrations.AddIndex(
            model_name="payment",
            index=models.Index(fields=["tenant", "paid_at"], name="payment_tenant_paid_idx"),
        ),
        migrations.AddIndex(
            model_name="adminauditlog",
            index=models.Index(fields=["timestamp", "id"], name="audit_timestamp_id_idx"),
        ),
        migrations.AddIndex(
            model_name="adminauditlog",
            index=models.Index(fields=["tenant_id", "timestamp"], name="audit_tenant_time_idx"),
        ),
        migrations.AddIndex(
            model_name="radiussession",
            index=models.Index(fields=["tenant", "customer", "stopped_at"], name="radius_tenant_customer_idx"),
        ),
        migrations.AddIndex(
            model_name="radiussession",
            index=models.Index(fields=["tenant", "acct_session_id", "stopped_at"], name="radius_tenant_acct_idx"),
        ),
        migrations.AddIndex(
            model_name="ticket",
            index=models.Index(fields=["tenant", "status", "created_at"], name="ticket_tenant_state_idx"),
        ),
    ]
