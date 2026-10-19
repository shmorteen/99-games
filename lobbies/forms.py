"""Small browser forms for the existing lobby service."""

from django import forms


class PublicLobbyCreateForm(forms.Form):
    name = forms.CharField(max_length=120, strip=True, label="Lobby name")
    request_id = forms.UUIDField(widget=forms.HiddenInput)
