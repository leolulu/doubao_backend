class Message:
    def __init__(self, system_message=None) -> None:
        self._messages = []
        self._messages_system_part = []
        self._messages_user_and_assistant_part = []
        if system_message:
            self._messages_system_part.append(self.construct_system_message(system_message))

    def construct_user_message(self, message):
        return {"role": "user", "content": message}

    def construct_assistant_message(self, message):
        return {"role": "assistant", "content": message}

    def construct_system_message(self, message):
        return {"role": "system", "content": message}

    def preserve_history(self, question, answer):
        self._messages_user_and_assistant_part.append(self.construct_user_message(question))
        self._messages_user_and_assistant_part.append(self.construct_assistant_message(answer))

    @property
    def messages(self):
        return self._messages_system_part + self._messages_user_and_assistant_part

    def generate_messages_jar(self, message):
        return self.messages + [self.construct_user_message(message)]
