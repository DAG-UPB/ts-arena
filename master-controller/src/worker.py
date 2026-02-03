import os
import time
import logging
import httpx
import docker

# Configure logging for clean output
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

TARGET_LABEL = os.environ.get("TARGET_LABEL", "managed.by=controller")

# Prefer from_env so DOCKER_HOST=http://docker-proxy:2375 is used
client = docker.from_env()

class Worker:
    """
    Manages the lifecycle of a Docker container-based prediction worker using Docker SDK.

    This class can be used as a context manager (with a `with` statement),
    to ensure that the Docker container is started before the prediction
    and properly shut down afterwards.
    """
    def __init__(self, service_name: str, base_url: str, port: int = 8000, timeout: float = 300):
        """
        Initializes the worker.

        Args:
            service_name (str): The name of the Docker service (e.g. 'chronos-bolt').
            base_url (str): The base URL for the prediction endpoint (e.g. 'http://localhost').
            port (int, optional): The port on which the worker's API runs. Default is 8000.
            timeout (float, optional): Timeout for HTTP requests in seconds. Default is 120.0.
        """
        self.service_name = service_name
        self.base_url = base_url
        self.port = port
        self.predict_url = f"{self.base_url}:{self.port}/predict"
        self.timeout = timeout
        self.container = None

    def __enter__(self):
        """Starts the container and returns the Worker object."""
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Stops the container when the `with` block is exited."""
        self.stop()

    def start(self):
        """Starts the worker container and waits until it is operational (healthy)."""
        logging.info(f"Starting container '{self.service_name}'...")
        logging.info(f"Available containers: {[c.name for c in client.containers.list(all=True)]}")
        # Find the container by name (assuming container name matches service_name)
        try:
            self.container = client.containers.get(self.service_name)
        except docker.errors.NotFound:
            logging.error(f"Container '{self.service_name}' not found.")
            raise RuntimeError(f"Container '{self.service_name}' not found.")

        if self.container.status != "running":
            self.container.start()

        logging.info(f"Waiting for container '{self.service_name}' to be reachable at {self.base_url}:{self.port}...")

        # Query a /health endpoint
        health_url = f"{self.base_url}:{self.port}/health"
        start_time = time.time()

        while time.time() - start_time < self.timeout:
            try:
                # Try to reach the health endpoint
                response = httpx.get(health_url, timeout=20)
                if response.status_code == 200:
                    logging.info(f"Container '{self.service_name}' is ready and responding on {health_url}.")
                    return
                else:
                    logging.warning(f"Container '{self.service_name}' health check failed with status {response.status_code}: {response.text}. Retrying...")
                    time.sleep(1)  

            except httpx.RequestError:
                # Normal while starting
                time.sleep(1)
            except Exception as e:
                logging.error(f"An unexpected error occurred while waiting for container '{self.service_name}': {e}")
                self.stop()
                raise

        # Timeout
        logging.error(f"Container '{self.service_name}' was not reachable after {self.timeout} seconds.")
        self.stop()
        raise RuntimeError(f"Timeout waiting for container '{self.service_name}'.")

    def stop(self):
        """Stops the worker container."""
        if self.container:
            self.container.reload()
            if self.container.status == "running":
                logging.info(f"Stopping container '{self.service_name}'...")
                self.container.stop(timeout=10)
                logging.info(f"Container '{self.service_name}' stopped.")
            else:
                logging.info(f"Container '{self.service_name}' is not running.")
        else:
            logging.info(f"No container to stop for '{self.service_name}'.")

    def predict(self, data=None):
        """
        Sends a prediction request to the worker.

        Args:
            data (dict, optional): The data for the prediction. If None, a GET request
                                   is sent. Otherwise a POST request with the data as JSON.

        Returns:
            The JSON response from the worker.
        """
        logging.info(f"Requesting prediction from '{self.service_name}'...")
        try:
            if data is None:
                response = httpx.get(self.predict_url, timeout=self.timeout)
            else:
                response = httpx.post(self.predict_url, json=data, timeout=self.timeout)

            response.raise_for_status()
            prediction = response.json()
            logging.info(f"Prediction from '{self.service_name}' received.")
            return prediction
        except httpx.RequestError as e:
            logging.error(f"HTTP request to '{self.service_name}' failed: {e}")
            raise


def list_targets():
    """List all containers with the target label."""
    return client.containers.list(all=True, filters={"label": [TARGET_LABEL]})


def ensure_started():
    """Ensure all target containers are started."""
    for c in list_targets():
        c.reload()
        if c.status != "running":
            logging.info(f"Starting container '{c.name}'...")
            c.start()


def ensure_stopped(timeout=10):
    """Ensure all target containers are stopped."""
    for c in list_targets():
        c.reload()
        if c.status == "running":
            logging.info(f"Stopping container '{c.name}'...")
            c.stop(timeout=timeout)


if __name__ == "__main__":
    # Example: Start, wait, stop again
    ensure_started()
    time.sleep(2)
    ensure_stopped()