from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('pokerlog', '0005_remove_ev_profit'),
    ]

    operations = [
        migrations.CreateModel(
            name='Venue',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='venues', to='auth.user')),
            ],
            options={
                'ordering': ['name'],
                'unique_together': {('user', 'name')},
            },
        ),
        migrations.AddField(
            model_name='entry',
            name='venue',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='entries', to='pokerlog.venue'
            ),
        ),
    ]
