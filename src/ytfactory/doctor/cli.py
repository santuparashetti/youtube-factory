"""Doctor CLI command."""

from ytfactory.doctor.pipeline import DoctorPipeline


def doctor():
    """Run health checks on the YouTube Factory environment."""
    DoctorPipeline().run()
