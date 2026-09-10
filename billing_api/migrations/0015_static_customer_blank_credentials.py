from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("billing_api", "0014_remove_payment_paystack_access_code_and_more"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="customer",
            name="unique_customer_username_per_tenant",
        ),
        migrations.AddConstraint(
            model_name="customer",
            constraint=models.UniqueConstraint(
                condition=~models.Q(service_type="static"),
                fields=("tenant", "username"),
                name="unique_customer_username_per_tenant",
            ),
        ),
    ]
