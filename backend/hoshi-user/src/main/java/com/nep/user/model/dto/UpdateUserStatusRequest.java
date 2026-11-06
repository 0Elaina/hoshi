package com.nep.user.model.dto;

import com.nep.user.model.enums.UserStatus;

import jakarta.validation.constraints.NotNull;

public record UpdateUserStatusRequest(
                @NotNull(message = "账号状态不能为空") UserStatus status) {

}
