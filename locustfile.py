from locust import HttpUser, constant, task


class Visitor(HttpUser):
    wait_time = constant(1)

    @task
    def request(self):
        self.client.get('/')
