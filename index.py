"""Vercel discovers this Flask app; containers continue to use wsgi:app."""

from app.vercel import create_vercel_app

app = create_vercel_app()
