package com.nep.user.dto;

import jakarta.validation.constraints.Size;

public record UpdateUserNicknameRequest(
        @Size(max = 32, message = "昵称长度不能超过32个字符") String nickname) {

    public UpdateUserNicknameRequest {
        nickname = nickname == null ? null : nickname.strip();
    }
}
