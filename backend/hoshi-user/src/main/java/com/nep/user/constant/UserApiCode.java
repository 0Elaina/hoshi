package com.nep.user.constant;

import org.springframework.http.HttpStatus;

import com.nep.common.api.ApiCode;

public final class UserApiCode {
    private UserApiCode() {
    }

    public static final ApiCode USERNAME_TAKEN = new ApiCode(HttpStatus.CONFLICT, "USERNAME_TAKEN", "用户名已被占用");
}
