"""
Three mechanics the quest types could not express on their own.

- **Quest chains**: a quest can wait on other quests of the same pass (`after`, `after_logic`). Until
  they are done it is shown locked and does not progress, exactly like a quest in a locked tier.
- **Crew-wide quests**: `shared_with_crew` moves the counter to the crew. `CrewQuest` is that counter;
  each member's own `PlayerQuest` mirrors it, so claiming and resetting work unchanged.
- **Drawn targets**: `draw_treasure` draws one treasure out of the quest's own filters for each player,
  kept on their progress row (`drawn_ball`), so nobody can copy anybody's answer.

Only new columns, one new table and one join table. Nothing already stored changes meaning.
"""

import django.db.models.deletion
from django.db import migrations, models

LOGIC = [("all", "All required"), ("any", "Any one required")]


class Migration(migrations.Migration):
    dependencies = [
        ("eventpass_app", "0017_new_quest_types"),
        ("crew_app", "0013_crew_role"),
        ("bd_models", "0026_credits_colour"),
    ]

    operations = [
        migrations.AddField(
            model_name="quest",
            name="after",
            field=models.ManyToManyField(
                blank=True,
                help_text=(
                    "The quests that have to be completed before this one opens. A quest still shut is shown "
                    "locked, says what it waits for, and does not progress — exactly like a quest in a locked "
                    "tier. Leave empty for a quest open from the start."
                ),
                related_name="opens",
                to="eventpass_app.quest",
                verbose_name="opens after",
            ),
        ),
        migrations.AddField(
            model_name="quest",
            name="after_logic",
            field=models.CharField(
                choices=LOGIC,
                default="all",
                help_text="Whether every quest above has to be completed, or any one of them.",
                max_length=3,
                verbose_name="opens after (logic)",
            ),
        ),
        migrations.AddField(
            model_name="quest",
            name="shared_with_crew",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "The progress belongs to the crew, not to the player: every member's deeds add to one "
                    "counter, and it completes for all of them. A player with no crew cannot move it, and cannot "
                    "finish it. Only for the quests that count an action — what a player owns or ranks at is "
                    "theirs alone."
                ),
                verbose_name="counted for the whole crew",
            ),
        ),
        migrations.AddField(
            model_name="quest",
            name="draw_treasure",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Instead of accepting any treasure matching the filters, one of them is drawn for each "
                    "player and the quest asks for that one. The filters are the pool it is drawn from, so a "
                    "group or a rarity range is needed. Nobody can copy anybody's answer, which is the point. "
                    "Catch, obtain and own only."
                ),
                verbose_name="draw a target for each player",
            ),
        ),
        migrations.AddField(
            model_name="playerquest",
            name="drawn_ball",
            field=models.ForeignKey(
                blank=True,
                help_text=(
                    "For a quest that draws a target: the treasure this player was given. Drawn once and never "
                    "again, so nobody can reroll a target they do not like by waiting."
                ),
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="bd_models.ball",
            ),
        ),
        migrations.CreateModel(
            name="CrewQuest",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "period",
                    models.CharField(
                        blank=True,
                        default="",
                        help_text='Empty for a one-off quest, "2026-09-20" for a daily one.',
                        max_length=16,
                    ),
                ),
                (
                    "progress",
                    models.PositiveBigIntegerField(default=0, help_text="How far the crew is, against the goal."),
                ),
                (
                    "completed_at",
                    models.DateTimeField(blank=True, help_text="When the crew reached the goal.", null=True),
                ),
                (
                    "crew",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="event_pass_quests",
                        to="crew_app.crew",
                    ),
                ),
                (
                    "quest",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="crew_progress",
                        to="eventpass_app.quest",
                    ),
                ),
            ],
            options={"db_table": "eventpasscrewquest", "managed": True},
        ),
        migrations.AddIndex(
            model_name="crewquest",
            index=models.Index(fields=["quest", "crew"], name="eventpass_cq_quest_idx"),
        ),
        migrations.AlterUniqueTogether(
            name="crewquest",
            unique_together={("quest", "crew", "period")},
        ),
    ]
