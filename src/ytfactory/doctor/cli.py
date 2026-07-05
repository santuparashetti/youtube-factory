from ytfactory.doctor.pipeline import DoctorPipeline


def doctor():
    """Run health checks."""
    DoctorPipeline().run()
