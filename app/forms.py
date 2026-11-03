from email_validator import EmailNotValidError, validate_email
from flask_wtf import FlaskForm
from wtforms import (
    HiddenField,
    IntegerField,
    PasswordField,
    SelectField,
    StringField,
    TextAreaField,
)
from wtforms.fields import SelectChoice
from wtforms.validators import (
    DataRequired,
    InputRequired,
    Length,
    NumberRange,
    Regexp,
    ValidationError,
)


def trimmed(value):
    if isinstance(value, str) and "\x00" in value:
        raise ValueError("Text cannot contain NUL characters.")
    return value.strip() if value else value


def email_syntax(form, field):
    # Reserved .test addresses are intentional fictional development identities.
    try:
        validate_email(field.data, check_deliverability=False, test_environment=True)
    except EmailNotValidError as exc:
        raise ValidationError("Invalid email address.") from exc


class LoginForm(FlaskForm):
    email = StringField(
        "Email", validators=[DataRequired(), email_syntax, Length(max=254)], filters=[trimmed]
    )
    password = PasswordField("Password", validators=[DataRequired(), Length(max=128)])


class ActionForm(FlaskForm):
    version = HiddenField("Version", validators=[DataRequired(), Regexp(r"^[0-9]{1,10}$")])


class ItemForm(ActionForm):
    code = StringField("Code", validators=[DataRequired(), Length(max=40)], filters=[trimmed])
    name = StringField("Name", validators=[DataRequired(), Length(max=160)], filters=[trimmed])
    kind = SelectField(
        "Kind",
        choices=[
            SelectChoice("component", "Component"),
            SelectChoice("finished", "Finished"),
            SelectChoice("packaging", "Packaging"),
        ],
    )


class UnitForm(ActionForm):
    code = StringField("Code", validators=[DataRequired(), Length(max=20)], filters=[trimmed])
    name = StringField("Name", validators=[DataRequired(), Length(max=80)], filters=[trimmed])
    dimension = StringField(
        "Dimension", validators=[DataRequired(), Length(max=30)], filters=[trimmed]
    )
    decimal_places = IntegerField(
        "Decimal places", validators=[InputRequired(), NumberRange(min=0, max=6)]
    )


class VariantForm(ActionForm):
    sku = StringField("SKU", validators=[DataRequired(), Length(max=80)], filters=[trimmed])
    revision = StringField(
        "Revision", validators=[DataRequired(), Length(max=40)], filters=[trimmed]
    )
    description = TextAreaField("Description", validators=[Length(max=4000)], filters=[trimmed])
    item_id = SelectField("Item", validators=[DataRequired()])
    base_unit_id = SelectField("Base unit", validators=[DataRequired()])
