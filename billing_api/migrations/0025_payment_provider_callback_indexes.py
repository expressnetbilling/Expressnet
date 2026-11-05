# Generated manually: provider callback correlation must remain fast as the
# payment ledger grows.

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("billing_api", "0024_adminauditlog_actor_tenant")]

    operations = [
        migrations.AlterField(
            model_name="payment",
            name="checkout_request_id",
            field=models.CharField(blank=True, db_index=True, max_length=255, null=True),
        ),
        migrations.AlterField(
            model_name="payment",
            name="paystack_reference",
            field=models.CharField(blank=True, db_index=True, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name="payment",
            name="tenant_settlement_provider",
            field=models.CharField(blank=True, db_index=True, max_length=32, null=True),
        ),
        migrations.AddField(
            model_name="payment",
            name="tenant_settlement_originator_conversation_id",
            field=models.CharField(blank=True, db_index=True, max_length=100, null=True),
        ),
        migrations.AddField(
            model_name="payment",
            name="tenant_settlement_conversation_id",
            field=models.CharField(blank=True, db_index=True, max_length=100, null=True),
        ),
    ]
