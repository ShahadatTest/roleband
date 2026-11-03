"""Response contracts for API routes, one module per domain.

A model here is what a route really sends, not what a client wishes it sent:
`tests/test_api_job_contract.py` drives the routes over HTTP and fails when a
serializer and its model disagree in either direction.
"""
