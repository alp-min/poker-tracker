from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('pokerlog', '0003_profile'),  # adjust if your last migration has a different name
    ]

    operations = [
        migrations.AddField(
            model_name='entry',
            name='currency',
            field=models.CharField(
                choices=[('GBP', '£ GBP'), ('USD', '$ USD')],
                default='GBP',
                max_length=3,
            ),
        ),
        migrations.AddField(
            model_name='profile',
            name='default_currency',
            field=models.CharField(
                choices=[('GBP', '£ GBP'), ('USD', '$ USD')],
                default='GBP',
                help_text='Default currency for new sessions',
                max_length=3,
            ),
        ),
    ]
