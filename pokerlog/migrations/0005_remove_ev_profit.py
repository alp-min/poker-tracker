from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('pokerlog', '0004_currency'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='entry',
            name='ev_profit',
        ),
    ]
